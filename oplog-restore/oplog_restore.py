from contextlib import suppress
import os
import subprocess
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from google.cloud import storage
import re
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def get_env_variables():
    try:
        env_vars = {
            "FULL_DUMP_URI": os.getenv("FULL_DUMP_URI"),
            "ACTION": os.getenv("ACTION"),
            "MONGO_URI": os.getenv("MONGO_URI"),
            "OPLOG_BUCKET_NAME": os.getenv("OPLOG_BUCKET_NAME"),
            "ENV": os.getenv("ENV"),
            "END_TIME": os.getenv("END_TIME"),
        }

        if (
            (not env_vars["FULL_DUMP_URI"])
            or (not env_vars["ACTION"])
            or ((not env_vars["MONGO_URI"]))
        ):
            raise ValueError(
                "Missing required environment variable: FULL_DUMP_URI, ACTION, MONGO_URI"
            )
        valid_actions = ["FULL_RESTORE", "OPLOG_REPLAY"]
        if env_vars["ACTION"] not in valid_actions:
            raise ValueError(
                f"Invalid value for ACTION. Allowed values: {', '.join(valid_actions)}"
            )

        if env_vars["ACTION"] == "OPLOG_REPLAY":
            if (not env_vars["OPLOG_BUCKET_NAME"]) or (not env_vars["ENV"]):
                raise ValueError(
                    "Missing required environment variable for OPLOG_REPLAY: OPLOG_BUCKET_NAME, ENV"
                )
        return env_vars
    except ValueError as e:
        raise RuntimeError(f"Error getting environment variables: {e}") from e


def download_gcs_backup(bucket_name, object_name):
    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        local_filename = f"/tmp/{bucket_name}/{object_name})"
        local_dir = os.path.dirname(local_filename)
        os.makedirs(local_dir, exist_ok=True)
        logging.info(f"Downloading {object_name} from GCS bucket {bucket_name}...")
        blob.download_to_filename(local_filename)
        logging.info(f"Backup saved as {local_filename}")
        return local_filename
    except Exception as e:
        raise RuntimeError(f"Error downloading backup from GCS: {e}")


def replay_oplgs(oplog_file, MONGO_URI, end_time: datetime):
    try:
        end_time_timestamp = int(end_time.timestamp())
        oplog_dir = os.path.dirname(oplog_file)
        replay_cmd = [
            "mongorestore",
            f"--uri={MONGO_URI}",
            f"--oplogReplay",
            f'--oplogLimit="{end_time_timestamp}:0"',
            f"--oplogFile={oplog_file}",
            f"--dir={oplog_dir}/",
        ]
        logging.info(f"Replaying oplogs from dir {oplog_dir}")
        subprocess.run(
            replay_cmd, check=True, stdout=subprocess.DEVNULL, stderr=sys.stderr
        )
        logging.info(f"Oplog Replay completed from file {oplog_file}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error replaying oplogs: {e}")


def restore_fulldump(backup_file, MONGO_URI):
    try:
        restore_cmd = [
            "mongorestore",
            f"--uri={MONGO_URI}",
            "--nsInclude=*",
            "--nsExclude=admin.system.*",
            "--nsExclude=admin.sessions.*",
            "--nsExclude=local.*",
            "--nsExclude=config.system.sessions",
            "--nsExclude=config.transactions",
            "--nsExclude=config.image_collection",
            "--nsExclude=config.system.indexBuilds",
            "--nsExclude=config.system.preimages",
            "--nsExclude=*.system.buckets",
            "--nsExclude=*.system.profile",
            "--nsExclude=*.system.views",
            "--nsExclude=*.system.js",
            "--gzip",
            f"--archive={backup_file}",
            "--drop",  # Drops existing collections before restoring
        ]
        logging.info("Restoring MongoDB from archive...")
        subprocess.run(restore_cmd, check=True, stderr=sys.stderr)
        logging.info("MongoDB Restore from Archive Completed!")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error restoring MongoDB: {e}")


def get_relevant_oplog_files(
    oplog_bucket_name, prefix, latest_backup_time, end_time: datetime
):

    try:
        client = storage.Client()
        bucket = client.bucket(oplog_bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)
    except Exception as e:
        raise RuntimeError(f"Failed to access GCS bucket '{oplog_bucket_name}': {e}")
    relevant_files = []
    timestamp_pattern = re.compile(
        r"(\d{4})/(\d{2})/(\d{2})/(\d{2})/(\d{2})/oplog\.bson$"
    )
    try:
        latest_backup_time = latest_backup_time.replace(tzinfo=timezone.utc)
    except Exception as e:
        raise ValueError(
            f"Invalid latest_backup_time: {latest_backup_time}. Error: {e}"
        )
    relevant_end_time = end_time + timedelta(hours=1)

    for blob in blobs:
        try:
            match = timestamp_pattern.search(blob.name)
            if match:
                year, month, day, hour, minute = map(int, match.groups())
                folder_timestamp = datetime(year, month, day, hour, minute).replace(
                    tzinfo=timezone.utc
                )
                if latest_backup_time < folder_timestamp < relevant_end_time:
                    relevant_files.append(blob.name)
        except ValueError as e:
            logging.warning(
                f"Skipping file {blob.name} due to timestamp parsing error: {e}"
            )
        except Exception as e:
            logging.error(f"Unexpected error processing file {blob.name}: {e}")

    return relevant_files


def get_full_backup_details(full_dump_uri: str):
    try:
        parsed_uri = urlparse(full_dump_uri)
        bucket_name = parsed_uri.netloc
        object_path = parsed_uri.path.lstrip("/")
        object_name = os.path.basename(object_path)
        match = re.search(r"(\d{8})_(\d{6})", object_name)
        if not match:
            raise ValueError(f"Timestamp not found in filename: {object_name}")
        timestamp_str = match.group(1) + match.group(2)
        try:
            backup_datetime = datetime.strptime(timestamp_str, "%Y%m%d%H%M%S")
        except ValueError as e:
            raise ValueError(f"Failed to parse timestamp from '{object_name}': {e}")
        return bucket_name, object_path, backup_datetime
    except ValueError as e:
        raise RuntimeError(f"Failed Parsing Full Dump URI: {e}") from e


if __name__ == "__main__":
    try:
        env_vars = get_env_variables()
        FULL_DUMP_URI = env_vars["FULL_DUMP_URI"]
        ACTION = env_vars["ACTION"]
        MONGO_URI = env_vars["MONGO_URI"]
        OPLOG_BUCKET_NAME = env_vars["OPLOG_BUCKET_NAME"]
        ENV = env_vars["ENV"]
        if env_vars["END_TIME"]:
            try:
                END_TIME = datetime.strptime(
                    env_vars["END_TIME"], "%Y/%m/%d %H:%M"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                raise ValueError(
                    f"Invalid END_TIME format: {env_vars['END_TIME']}. Expected format: YYYY/MM/DD HH:MM"
                )
        else:
            END_TIME = datetime.now(timezone.utc)

        full_dump_bucket_name, full_dump_object_path, backup_time = (
            get_full_backup_details(FULL_DUMP_URI)
        )
        if not all([full_dump_bucket_name, full_dump_object_path, backup_time]):
            logging.error("No valid full backup found. Exiting recovery process.")
            exit(1)
        logging.info(
            f"full backup details: Bucket:{full_dump_bucket_name} Timestamp: {backup_time} Object: {full_dump_object_path}"
        )
        if ACTION == "FULL_RESTORE":
            try:
                full_dump_file = download_gcs_backup(
                    full_dump_bucket_name, full_dump_object_path
                )
                restore_fulldump(full_dump_file, MONGO_URI)
            except Exception as e:
                logging.error(f"Error restoring full dump: {e}")
                exit(1)
            finally:
                with suppress(FileNotFoundError):
                    if os.path.exists(full_dump_file):
                        os.remove(full_dump_file)
                        logging.info(f"Deleted file: {full_dump_file}")

        if ACTION == "OPLOG_REPLAY":
            relevant_files = get_relevant_oplog_files(
                OPLOG_BUCKET_NAME, ENV, backup_time, END_TIME
            )
            if not relevant_files:
                logging.warning("No oplog files found for the given timeframe.")
            logging.info(relevant_files)
            for file in relevant_files:
                try:
                    oplog_file = download_gcs_backup(OPLOG_BUCKET_NAME, file)
                    replay_oplgs(oplog_file, MONGO_URI, END_TIME)
                except Exception as e:
                    logging.error(f"Failed to apply oplog {file}: {e}")
                    exit(1)
                finally:
                    with suppress(FileNotFoundError):
                        if oplog_file:
                            os.remove(oplog_file)
                            logging.info(f"Deleted file: {oplog_file}")
            logging.info("MongoDB restore process completed successfully!")
    except Exception as e:
        logging.error(f"Unexpected error in MongoDB restore script: {e}")
        exit(1)
