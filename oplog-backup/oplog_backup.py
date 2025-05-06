import os
import subprocess
import json
import sys
from datetime import datetime, timedelta, timezone
import logging
from google.cloud import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def calculate_timestamps(INTERVAL):
    end_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_time = end_time - timedelta(minutes=INTERVAL)
    return int(start_time.timestamp()), int(end_time.timestamp())


def get_env_variables():
    env_vars = {
        "ENV": os.getenv("ENV"),
        "BUCKET_NAME": os.getenv("BUCKET_NAME"),
        "MONGO_URI": os.getenv("MONGO_URI"),
        "INTERVAL_IN_MINS": os.getenv("INTERVAL_IN_MINS", "60"),
    }
    missing_vars = [key for key, value in env_vars.items() if not value]
    if missing_vars:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )
    return env_vars


def upload_to_gcs(ENV, bucket_name, file_path, end_time):
    try:
        utc_time = datetime.fromtimestamp(end_time, tz=timezone.utc)
        file_name = os.path.basename(file_path)
        bucket_path = utc_time.strftime("%Y/%m/%d/%H/%M")
        destination_blob_name = f"{ENV}/{bucket_path}/{file_name}"
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        logging.info(
            f"Uploading {file_path} to gs://{bucket_name}/{destination_blob_name} ..."
        )
        blob.upload_from_filename(file_path)
        logging.info("Upload complete!")
    except Exception as e:
        raise RuntimeError(f"Error uploading to GCS: {e}")


def dump_oplogs(MONGO_URI, query):
    query_string = json.dumps(query)
    BACKUP_DIR = "/tmp/backup"
    BACKUP_FILE = f"{BACKUP_DIR}/oplog.bson"
    mongo_cmd = [
        "mongodump",
        f"--uri={MONGO_URI}",
        "--db=local",
        "--collection=oplog.rs",
        f"--query={query_string}",
        "-o",
        "-",
    ]
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        with open(BACKUP_FILE, "wb") as output:
            subprocess.run(mongo_cmd, check=True, stdout=output, stderr=sys.stderr)
        logging.info("Dump Completed !")
        return BACKUP_FILE
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        raise RuntimeError(f"Error taking MongoDB backup: {error_msg}")


if __name__ == "__main__":
    try:
        env_vars = get_env_variables()
        ENV = env_vars["ENV"]
        BUCKET_NAME = env_vars["BUCKET_NAME"]
        MONGO_URI = env_vars["MONGO_URI"]
        INTERVAL_IN_MINS = (
            int(env_vars["INTERVAL_IN_MINS"])
            if env_vars["INTERVAL_IN_MINS"].isdigit()
            else env_vars["INTERVAL_IN_MINS"]
        )
        start_time, end_time = calculate_timestamps(INTERVAL_IN_MINS)
        print(start_time, end_time)
        query = {
            "ts": {
                "$gte": {"$timestamp": {"t": start_time, "i": 1}},
                "$lte": {"$timestamp": {"t": end_time, "i": 0}},
            }
        }
        BACKUP_FILE = dump_oplogs(MONGO_URI, query)
        upload_to_gcs(ENV, BUCKET_NAME, BACKUP_FILE, end_time)
    except Exception as e:
        logging.error(f"Error : {e}")
        exit(1)
