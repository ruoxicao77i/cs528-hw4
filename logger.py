import json
import threading

from google.cloud import pubsub_v1, storage
from google.cloud.exceptions import NotFound

BUCKET_NAME = "cs528-ruoxi-pagerank"
LOG_BLOB = "forbidden/forbidden-requests.log"
SUBSCRIPTION_ID = "forbidden-requests-sub"

storage_client = storage.Client()
subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(storage_client.project, SUBSCRIPTION_ID)

write_lock = threading.Lock()


def append_to_bucket(line: str):
    """Append one line to the log file in the bucket."""
    bucket = storage_client.bucket(BUCKET_NAME)
    with write_lock:
        # get_blob fetches fresh metadata, including the current generation,
        # so the download below asks for that exact version, not a cached one
        current = bucket.get_blob(LOG_BLOB)
        old_lines = current.download_as_text() if current else ""

        log_file = bucket.blob(LOG_BLOB)
        log_file.cache_control = "no-store"
        log_file.upload_from_string(old_lines + line + "\n", content_type="text/plain")

def callback(message):
    data = json.loads(message.data.decode("utf-8"))
    line = (f"[{data['time']}] ERROR: forbidden request from {data['country']}: "
            f"{data['method']} {data['target']}")
    print(line, flush=True)
    append_to_bucket(line)
    message.ack()


def main():
    streaming_pull = subscriber.subscribe(subscription_path, callback=callback)
    print(f"Listening on {subscription_path} (Ctrl+C to stop)")
    with subscriber:
        try:
            streaming_pull.result()      # blocks forever
        except KeyboardInterrupt:
            streaming_pull.cancel()
            streaming_pull.result()


if __name__ == "__main__":
    main()