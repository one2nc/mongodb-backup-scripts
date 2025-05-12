# MongoDB Backup, Restore & Validation Toolkit

## Overview

This repository contains a comprehensive set of scripts to manage MongoDB **backups**, **restorations**, and **post-backup validations**. It supports both **full database dumps** and **oplog backups** for point-in-time recovery (PITR), along with a script to inspect and validate database metadata.

The backup and restore operations are containerized and can be automated using **Kubernetes CronJobs**, making them production-ready for scheduled operations in cloud-native environments. All backup data is stored in **Google Cloud Storage (GCS)**.

---

## Table of Contents

1. [MongoDB Database & Collection Metadata Script](#mongodb-database--collection-metadata-script)
2. [MongoDB Full Load Backup](#mongodb-full-load-backup)
3. [MongoDB Oplog Backup](#mongodb-oplog-backup)
4. [MongoDB Restore Script](#mongodb-restore-script)

---


## MongoDB Database & Collection Metadata Script
### Prerequisites 
- `mongosh` Shell 
- Credentials with atleast **read acess** to all databases.

### Description
This script iterates over all non-system databases in a MongoDB instance and generates a detailed JSON summary of their collections.  
It is especially useful for **backup validation** and general metadata inspection. 
It captures following key information:
- Number of documents in each collection
- Size of each collection (in bytes)
- Minimum and Maximum `_id` values

### Usage 
```bash
mongosh <CONNECTION_STRING> db_stats.js
```
The output will be printed as formatted JSON to the terminal.

## MongoDB Full Load Backup

We have automated MongoDB Full Load Backups to GCS Buckets using a python Script. This script is scheduled to run as a Kubernetes CronJob.

### Prerequisites

- GCS Bucket to store backups.
- Necessary permission to access GCS Bucket.

### Setup Details

- Full Backup script will simply take MongoDB backup using `mongodump` (version 100.11.0) utility and copy it to GCS Bucket.
- Backup File Format with timestamp : `/<APP_NANE>/<ENV>/mongodb_backup_<yyyymmdd_HHMMSS>.gz`
- **Script Details** :
  - _Script Path_ : `full-backup/full-backup.py`
  - _Environment Variables_ : Following are the required environment variables
    - **MONGO_URI** (string) : MongoDB connection String
    - **BUCKET_NAME** (string) : GCS Bucket Name
    - **ENV** (string) and **APP_NAME** (string) : Using these env variables backup storage path will be `/<APP_NAME>/<ENV>/<FILE_NAME>`
- Dockerfile Path : `Dockerfile-Full-Backup`
- Kubernetes Manifests : `kubernetes-manifests/full-backup-cronjob-template.yml`

## MongoDB Oplog Backup

We have implemented automated MongoDB Oplog Backups using a Python script that runs as a Kubernetes CronJob. This script periodically queries the MongoDB oplog collection and uploads the extracted logs to a GCS Bucket. These oplog backups enable near Point-in-Time Recovery (PITR) when combined with full backups.

### Prerequisites

- A GCS Bucket to store oplog backups.
- Necessary permissions to access the GCS Bucket.
- MongoDB must be running as a replica set (as oplogs are only available in replica sets).

### Setup Details

- The script queries the `local.oplog.rs` collection to extract oplogs generated within a specific time interval.
- This interval is controlled by the environment variable `INTERVAL_IN_MINS` (default: 60).
- **Timestamp Calculation** :

  - The script determines the end timestamp by rounding the current UTC time down to the nearest hour.
  - The start timestamp is calculated by subtracting `INTERVAL_IN_MINS` from the end timestamp.
  - This ensures a clean, non-overlapping window and helps align oplog backups with monitoring and recovery strategies.
  - For Example, If the script runs at `11:17 AM` UTC and `INTERVAL_IN_MINS=60`, the backup window is from `10:00:00` to `11:00:00` UTC.

- Oplogs are backed up using the `mongodump` (version 100.11.0) utility and stored in a GCS bucket in BSON format.
- Backup file path format: `/<ENV>/YYYY/MM/DD/HH/MM/oplog.bson`.
- **Script Details** :
  - _Script Path_: `oplog-backup/oplog-backup.py`
  - _Environment Variables_ :
    - **MONGO_URI** (string) : MongoDB Connection String
    - **BUCKET_NAME** (string) : GCS Bucket Name
    - **ENV** (string) : Environment name (used in the GCS path)
    - **INTERVAL_IN_MINS** (string,optional) : Duration (in minutes) of the oplog window to back up. Default is `60`.
- Dockerfile Path : `Dockerfile-Oplog-Backup`
- Kubernetes Manifests : `kubernetes-manifests/oplog-backup-cronjob-template.yml`

## MongoDB Restore Script

This script automates the restoration of MongoDB databases from a full dump and optional oplog replay using backups stored in Google Cloud Storage (GCS).

It supports two restoration modes:

- **FULL_RESTORE** : Restore from full `mongodump` archive.
- **OPLOG_REPLAY** : Apply oplogs after the full restore to catch up to a more recent point in time.

### Prerequisites

- GCS buckets storing full dump archives and oplog backups.
- Kubernetes service account with required IAM permissions to access the GCS buckets.
- MongoDB URI with appropriate permissions to perform restores and oplog replays.

### Setup Details

- The script pulls the full dump from a GCS bucket using the provided URI, and optionally downloads and applies oplogs based on timestamp-based folder structure.
- Script automatically cleans up temporary files after each restore step.
- **Modes of Operation** :
  1. **FULL_RESTORE** : Restores the entire MongoDB dump from an archived file (created using `mongodump --archive --gzip`) and drops existing collections.
  2. **OPLOG_REPLAY** : Fetches and applies relevant oplog files from the configured oplog bucket between:
  - Full dump timestamp (extracted from `FULL_DUMP_URI`)
  - Target `END_TIME` (defaults to current time if not provided)
- **Script Details** :
  - _Script Path_: `oplog_restore/oplog_restore.py`
  - _Environment Variables_ :
    - **MONGO_URI** (string) : (Required) MongoDB Connection String
    - **FULL_DUMP_URI** (string) : (Required) GCS URI to full backup file (e.g., `gs://<bucket>/<path>/mongodb_backup_20250404_010203.gz`)
    - **ACTION** (string) : (Required) One of: `FULL_RESTORE` or `OPLOG_REPLAY`.
    - **OPLOG_BUCKET_NAME** (string) : (Optional, Required when `ACTION==OPLOG_REPLAY`) Name of the GCS bucket where oplogs are stored.
    - **ENV** (string) : (Optional, Required when `ACTION==OPLOG_REPLAY`) Environment folder prefix (e.g., `preprod`, `prod`)
    - **END_TIME** (string) : (Optional) Timestamp (UTC) till which oplogs should be replayed. Format: `YYYY/MM/DD HH:MM`. Defaults to current UTC time.
- Dockerfile Path : `Dockerfile-Restore`