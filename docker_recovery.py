#!/usr/bin/python3

import glob
import os
import subprocess

DOCKER_VOLUME_DATA = "/var/lib/docker/volumes/services_{0}/_data"
LOG_DIR = "/var/log/rclone/recovery"
LOG_FILE = "/var/log/rclone/recovery/{0}.log"
DEFAULT_TIMEOUT = 21600 # 6 hours

backup_drives = {
  "bookstack": DOCKER_VOLUME_DATA.format("bookstack"),
  "bookstack_db": DOCKER_VOLUME_DATA.format("bookstack_db"),
  "caddy": DOCKER_VOLUME_DATA.format("caddy"),
  "fathom":DOCKER_VOLUME_DATA.format("fathom"),
  "isso": DOCKER_VOLUME_DATA.format("isso"),
  "gitea": "/var/lib/gitea",
  "minio": DOCKER_VOLUME_DATA.format("minio"),
  "minecraft": DOCKER_VOLUME_DATA.format("minecraft"),
}

def setup_logs():
  # Make log dir if doesn't already exist
  os.makedirs(LOG_DIR, exist_ok=True)

  # Delete previous logs
  files = glob.glob(LOG_DIR + "/*.log")
  for f in files:
    os.remove(f)

def recover():
  # Run rclone sync on all service drives
  for service in backup_drives:
    cmd = "rclone sync backup-secret:{0}/ {1} --fast-list --transfers 16 \
          --log-file {2} --log-level INFO".format(service, backup_drives[service], \
            LOG_FILE.format(service))

    subprocess.run(cmd, shell=True)

if __name__ == "__main__":
  setup_logs()
  recover()
