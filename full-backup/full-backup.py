import os
import subprocess
import datetime
from google.cloud import storage
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def get_env_variables():
    try:
        env_vars = {
            "MONGO_URI": os.getenv("MONGO_URI"),
            "BUCKET_NAME": os.getenv("BUCKET_NAME"),
            "ENV": os.getenv("ENV"),
            "APP_NAME": os.getenv("APP_NAME"),
        }
        missing_vars = [key for key, value in env_vars.items() if not value]
        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )
        return env_vars
    except ValueError as e:
        raise RuntimeError(f"Error getting environment variables: {e}")


def dump_mongo(MONGO_DATABASE_URL):
    try:
        BACKUP_DIR = "/tmp/mongodb_backup"
        TIMESTAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        BACKUP_FILE = f"{BACKUP_DIR}/mongodb_backup_{TIMESTAMP}.gz"
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
        except Exception as e:
            raise RuntimeError(f"Failed to create backup directory '{BACKUP_DIR}")

        dump_cmd = [
            "mongodump",
            f"--uri={MONGO_DATABASE_URL}",
            "--gzip",
            f"--archive={BACKUP_FILE}",
        ]

        logging.info("Running mongodump...")
        subprocess.run(dump_cmd, check=True, stdout=sys.stdout, stderr=sys.stderr)
        logging.info("MongoDB Backup Completed!")
        return BACKUP_FILE
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        raise RuntimeError(f"MongoDB backup failed: {error_msg}")


def upload_to_gcs(bucket_name, file_path, env, app_name):
    try:
        file_name = os.path.basename(file_path)
        destination_blob_name = f"{env}/{app_name}/{file_name}"
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


if __name__ == "__main__":
    try:
        env_vars = get_env_variables()
        BACKUP_FILE = dump_mongo(env_vars["MONGO_URI"])
        if env_vars["BACKUP_STORAGE"] == "GCS":
            upload_to_gcs(
                env_vars["BUCKET_NAME"],
                BACKUP_FILE,
                env_vars["ENV"],
                env_vars["APP_NAME"],
            )
    except Exception as e:
        logging.error(f"Error: {e}")
        exit(1)
