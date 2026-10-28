from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http import HTTPStatus
import os
import sys
import queue
import time
import threading
import functools
from datetime import datetime, timezone
import json

import pymysql
from google.cloud import storage
from google.cloud import logging as cloud_logging
from google.cloud import pubsub_v1
from google.cloud.exceptions import NotFound, Forbidden

# configurations for google cloud
storage_client = storage.Client()
logging_client = cloud_logging.Client()
cloud_logger = logging_client.logger("file-server")
FORBIDDEN_COUNTRIES = {
    "north korea", "iran", "cuba", "myanmar", "iraq",
    "libya", "sudan", "zimbabwe", "syria",
}
publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(storage_client.project, "forbidden-requests")

PORT = 8000


# ---------------------------------------------------------------------------
# Database configuration
# DB_HOST and DB_PASS come from environment variables (set by startup.sh),
# so no IP address or password is hardcoded in this file.
# ---------------------------------------------------------------------------
DB_HOST = os.environ.get("DB_HOST")
DB_USER = os.environ.get("DB_USER", "appuser")
DB_PASS = os.environ.get("DB_PASS")
DB_NAME = os.environ.get("DB_NAME", "hw5")

INSERT_REQUEST = """
    INSERT INTO requests
        (country, client_ip, gender, age, income, is_banned, time_of_day, requested_file)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

INSERT_FAILED = """
    INSERT INTO failed_requests (time_of_request, requested_file, error_code)
    VALUES (%s, %s, %s)
"""

_db_pool = queue.LifoQueue()

def _new_db_conn():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        autocommit=True,
        connect_timeout=10,
    )

def _run_sql(conn:pymysql.connect, query, params):
    with conn.cursor() as cur:
        cur.execute(query, params)

def db_execute(query, params):
    """Run one statement using a pooled connection, reconnecting once if it went stale."""
    try:
        conn = _db_pool.get_nowait()
    except queue.Empty:
        conn = _new_db_conn()

    try:
        _run_sql(conn, query, params)
    except (pymysql.err.OperationalError, pymysql.err.InterfaceError):
        try:
            conn.close()
        except Exception:
            pass
        conn = _new_db_conn()
        _run_sql(conn, query, params)

    _db_pool.put(conn)

def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

# ================
# Timing instrumentation
# time.perf_counter() is Python's high resolution timer. For every timed
# operation we keep count, total, min and max, shared by all threads.
# =================
class TimingStats:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}   # name -> [count, total_seconds, min_seconds, max_seconds]
 
    def add(self, name, seconds):
        with self._lock:
            d = self._data.get(name)
            if d is None:
                self._data[name] = [1, seconds, seconds, seconds]
            else:
                d[0] += 1
                d[1] += seconds
                d[2] = min(d[2], seconds)
                d[3] = max(d[3], seconds)

    def snapshot(self):
        with self._lock:
            return {
                name: {
                    "count": c,
                    "total_s": round(total, 3),
                    "avg_ms": round(total / c * 1000, 3),
                    "min_ms": round(mn * 1000, 3),
                    "max_ms": round(mx * 1000, 3),
                }
                for name, (c, total, mn, mx) in self._data.items()
            }

timing = TimingStats()
timing_logger = logging_client.logger("file-server-timing")

class timed:
    """Time a block of code:  with timed("name"): ..."""
    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.start = time.perf_counter()

    def __exit__(self, *exc):
        timing.add(self.name, time.perf_counter() - self.start)
        return False

def timed_func(name):
    """Decorator verson of timed(), used on the four instrumented functions."""
    def wrap(func):
        @functools.wraps(func)
        def inner(*args, **kwargs):
            with timed(name):
                return func(*args, **kwargs)
        return inner
    return wrap

def report_timing():
    """Send the current timing summary to Cloud Logging and stdout."""
    snap = timing.snapshot()
    print("TIMING " + json.dumps(snap), flush=True)
    try:
        timing_logger.log_struct({"timing": snap, "time": datetime.now(timezone.utc).isoformat()})
    except Exception as e:
        print(f"Failed to write timing to Cloud Logging: {e}", flush=True)
 
 
def timing_reporter_loop(interval=60):
    """Background thread: report once a minute, but only if new requests came in."""
    last_count = 0
    while True:
        time.sleep(interval)
        count = timing.snapshot().get("1_extract_headers", {}).get("count", 0)
        if count != last_count:
            report_timing()
            last_count = count

class CustomHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """
        The method handles the GET request.
        The path of the file is in the URL.
        e.g. curl http://localhost:8000/my-bucket/hello.txt
        """
        self.handle_request(self.path)

    def do_POST(self):
        """
        The method handles the POST request.
        It assumes that the body of the POST request is the path of the file.
        e.g. curl -d "my-bucket/hello.txt" http://localhost:8000/
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return
        body = self.rfile.read(length).decode("utf-8")
        self.handle_request(body)
 
    # -----------------------------------------------------------------------
    # Main flow. Each step is its own function so it can be timed later:
    #   1. extract_request_info  -> process request, read headers
    #   2. read_from_storage     -> read the file from Cloud Storage
    #   3. send_reply            -> send the response to the client
    #   4. insert_into_db        -> write the request into the database
    # -----------------------------------------------------------------------
    def handle_request(self, path: str):
        self._in_request = True
        self._status = int(HTTPStatus.OK)   # send_error() overwrites this on failure
 
        info = self.extract_request_info(path)
        self.serve_file(info)
        self.insert_into_db(info)

    @timed_func("1_extract_headers")    
    def extract_request_info(self, path:str) -> dict:
        """Step 1: pull everything we need out of the request"""
        h = self.headers
        country = h.get("X-country", "").strip()
        return{
            "country": country or None,
            "client_ip": h.get("X-client-IP") or self.client_address[0],
            "gender": h.get("X-gender"),
            "age": h.get("X-age"),
            "income": h.get("X-income"),
            "time": h.get("X-time") or now_str(),
            "requested_file": path.strip(),
            "is_banned": country.lower() in FORBIDDEN_COUNTRIES,
        }
    
    def serve_file(self, info: dict):
        """Step 2: Shared by GET and POST: parse '<bucket>/<blob>' and send the file back."""
        path = info["requested_file"]
        bucket_name, _, blob_name = path.strip().lstrip("/").partition("/")
        target = f"{bucket_name}/{blob_name}"

        if info["is_banned"]:
            self.report_forbidden(target)
            self.send_error(
                HTTPStatus.BAD_REQUEST,
                f"Permission denied: requests from {info['country']} are not allowed",
            )
            return

        if not bucket_name or not blob_name:
            self.send_error(HTTPStatus.NOT_FOUND, f"File not found: {target}")
            return

        try:
            contents = self.read_from_storage(bucket_name, blob_name)
        except NotFound:
            self.send_error(HTTPStatus.NOT_FOUND, f"File not found: {target}")
            return
        except Forbidden:
            self.send_error(HTTPStatus.FORBIDDEN, f"Access denied: {target}")
            return
        except Exception as e:
            # keep the message to one short line, it also goes into the HTTP status line
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(e).__name__} while reading {target}")
            return

        # response
        self.send_reply(contents)
        
    @timed_func("2_read_storage")
    def read_from_storage(self, bucket_name: str, blob_name: str) -> bytes:
        """Downloads a blob into memory."""
        blob = storage_client.bucket(bucket_name).blob(blob_name)
        return blob.download_as_bytes()

    @timed_func("3_send_response")
    def send_reply(self, contents:bytes):
        """Step 3: send a 200 respone with the file contents"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(contents)))
        self.end_headers()
        self.wfile.write(contents)
        self.wfile.flush()

    @timed_func("4_insert_db")
    def insert_into_db(self, info: dict):
        """Step 4: log every request, and log failures into a second table."""
        try:
            db_execute(INSERT_REQUEST, (
                info["country"], info["client_ip"], info["gender"], info["age"],
                info["income"], info["is_banned"], info["time"], info["requested_file"],
            ))
            if self._status != HTTPStatus.OK:
                db_execute(INSERT_FAILED, (info["time"], info["requested_file"], self._status))
        except Exception as e:
            print(f"Failed to write to database: {e}", flush=True)

    def send_error(self, code, message=None, explain=None):
        """
        Every error response goes through here, including the 501 that
        http.server sends by itself for methods without a do_* function.
        Log it first, then let http.server build the response as usual.
        """
        if message is None:
            message = self.responses.get(code, ("???",))[0]
        self._status = int(code)
        self.log_to_cloud(code, message)
        # error responses are also "sending a response", so time them too
        with timed("3_send_response"):
            super().send_error(code, message, explain)
 
        # Errors raised outside handle_request (e.g. 501 for PUT, bad
        # Content-Length) never reach insert_into_db, so record them here.
        if not getattr(self, "_in_request", False):
            self.insert_failed_only(int(code))

    def insert_failed_only(self, code:int):
        headers = getattr(self, "headers", None)
        req_time = (headers.get("X-time") if headers else None) or now_str()
        try:
            db_execute(INSERT_FAILED, (req_time, getattr(self, "path", None), code))
        except Exception as e:
            print(f"Failed to write to database: {e}", flush=True)


    def log_to_cloud(self, code, message):
        """Log a structured Cloud Logging entry."""
        # for some malformed requests http.server fails before setting path/headers
        headers = getattr(self, "headers", None)
        try:
            cloud_logger.log_struct(
                {
                    "message": f"code {int(code)}, message {message}",
                    "status": int(code),
                    "method": self.command or None,
                    "path": getattr(self, "path", None),
                    "client_ip": self.client_address[0],
                    "country": headers.get("X-country") if headers else None,
                    "user_agent": headers.get("User-Agent") if headers else None,
                    "time": datetime.now(timezone.utc).isoformat(),
                },
                severity=self.severity_for(code),
            )
        except Exception as e:
            print(f"Failed to write to Cloud Logging: {e}", flush=True)

    def severity_for(self, code)->str:
        if code == HTTPStatus.BAD_REQUEST:
            return "CRITICAL"
        if code >=500:
            return "ERROR"
        return "WARNING"

    def report_forbidden(self, target: str):
        headers = getattr(self, "headers", None)
        message = {
            "country": headers.get("X-country", "") if headers else None,
            "method": self.command or None,
            "target": target or None,
            "time": datetime.now(timezone.utc).isoformat(),
        }
        try:
            future = publisher.publish(topic_path, json.dumps(message).encode("utf-8"))
            future.result(timeout=10)
        except Exception as e:
            print(f"Failed to publish to Pub/Sub: {e}", flush=True)


def run(HandlerClass=CustomHandler,
        ServerClass=ThreadingHTTPServer,
        protocol="HTTP/1.0", port=PORT, bind=""):
    """
    Run the HTTP server.

    bind="" listens on all network interfaces (shown as 0.0.0.0),
    which is what you want on a VM so it can be reached from outside.
    """
    HandlerClass.protocol_version = protocol
    with ServerClass((bind, port), HandlerClass) as httpd:
        host, port = httpd.socket.getsockname()[:2]
        url_host = f"[{host}]" if ":" in host else host
        print(f"Serving HTTP on {host} port {port} (http://{url_host}:{port}/) ...", flush=True)
        if host in ("0.0.0.0", "::"):
            print(f"Listening on all interfaces. On this machine, open http://localhost:{port}/", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nKeyboard interrupt received, exiting.")
            sys.exit(0)


if __name__ == "__main__":
    if not DB_HOST or not DB_PASS:
        sys.exit("Please set DB_HOST and DB_PASS environment variables first.")
    threading.Thread(target=timing_reporter_loop, daemon=True).start()
    run()