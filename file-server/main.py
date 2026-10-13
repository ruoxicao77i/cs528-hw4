from http.server import HTTPServer, BaseHTTPRequestHandler
from http import HTTPStatus
import sys
from datetime import datetime, timezone
import json

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

class CustomHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """
        The method handles the GET request.
        The path of the file is in the URL.
        e.g. curl http://localhost:8000/my-bucket/hello.txt
        """
        self.serve_file(self.path)

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
        self.serve_file(body)

    def serve_file(self, path: str):
        """Shared by GET and POST: parse '<bucket>/<blob>' and send the file back."""
        
        bucket_name, _, blob_name = path.strip().lstrip("/").partition("/")
        target = f"{bucket_name}/{blob_name}"

        if self.is_forbidden():
            country = self.headers.get("X-country", "").strip()
            self.report_forbidden(target)
            self.send_error(
                HTTPStatus.BAD_REQUEST,
                f"Permission denied: requests from {country} are not allowed",
            )
            return

        if not bucket_name or not blob_name:
            self.send_error(HTTPStatus.NOT_FOUND, f"File not found: {target}")
            return

        try:
            contents = self.download_blob_into_memory(bucket_name, blob_name)
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
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(contents)))
        self.end_headers()

        # contents
        self.wfile.write(contents)

    def send_error(self, code, message=None, explain=None):
        """
        Every error response goes through here, including the 501 that
        http.server sends by itself for methods without a do_* function.
        Log it first, then let http.server build the response as usual.
        """
        if message is None:
            message = self.responses.get(code, ("???",))[0]

        self.log_to_cloud(code, message)
        super().send_error(code, message, explain)


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

    def download_blob_into_memory(self, bucket_name: str, blob_name: str):
        """Downloads a blob into memory."""
        blob = storage_client.bucket(bucket_name).blob(blob_name)
        return blob.download_as_bytes()

    def is_forbidden(self) -> bool:
        country = self.headers.get("X-country", "").strip().lower()
        return country in FORBIDDEN_COUNTRIES

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
        ServerClass=HTTPServer,
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
    run()