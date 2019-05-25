#!/usr/bin/python3

import argparse
import base64
import glob
import os
import sendgrid
import subprocess
from datetime import datetime
from sendgrid.helpers.mail import *

DOCKER_VOLUME_DATA = "/var/lib/docker/volumes/services_{0}/_data"
LOG_DIR = "/var/log/rclone"
LOG_FILE = "/var/log/rclone/{0}.log"
DEFAULT_TIMEOUT = 600

EMAIL_SENDER = "backup@example.com"
EMAIL_RECIPIENT = "example@example.com"

backup_drives = {
  "bookstack": DOCKER_VOLUME_DATA.format("bookstack"),
  "bookstack_db": DOCKER_VOLUME_DATA.format("bookstack_db"),
  "caddy": DOCKER_VOLUME_DATA.format("caddy"),
  "fathom":DOCKER_VOLUME_DATA.format("fathom"),
  "isso": DOCKER_VOLUME_DATA.format("isso"),
  "gitea": "/var/lib/gitea",
  "minio": DOCKER_VOLUME_DATA.format("minio"),
}

def parse_args():
  parser = argparse.ArgumentParser()
  parser.add_argument("sendgrid_apikey", help="Sendgrid API key", type=str)
  args = parser.parse_args()
  return args.sendgrid_apikey

def setup_logs():
  # Make log dir if doesn't already exist
  os.makedirs(LOG_DIR, exist_ok=True)

  # Delete previous logs
  files = glob.glob(LOG_DIR + "/*.log")
  for f in files:
    os.remove(f)

def get_stats(service):
  # Get only the last 6 lines for transfer summary
  cmd = "tail -n 6 {0}".format(LOG_FILE.format(service))
  read_process = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE)
  return read_process.stdout.decode("utf-8")

def create_attachment(service):
  # Read log file and add as SendGrid attachment
  file_content = ""
  with open(LOG_FILE.format(service), "rb") as f:
    file_content = f.read()
    f.close()

  encoded = base64.b64encode(file_content).decode()
  attachment = Attachment()
  attachment.file_content = FileContent(encoded)
  attachment.file_type = FileType("text/plain")
  attachment.file_name = FileName("{0}_log.txt".format(service))
  return attachment

def send_result_email(api_key, subject, body, attachments):
  mail = Mail(
    from_email=EMAIL_SENDER,
    to_emails=EMAIL_RECIPIENT,
    subject=subject,
    plain_text_content=body)

  mail.attachment = attachments

  try:
    sendgrid_client = sendgrid.SendGridAPIClient(api_key)
    sendgrid_client.send(mail)
  except Exception as e:
    print(e)

def backup(api_key):
  backup_ran_with_errors = False
  return_codes = {}
  outputs = {}
  attachments = []

  start_time = datetime.now()

  # Run rclone sync on all service drives
  for service in backup_drives:
    cmd = "rclone sync {0} backup-secret:{1}/ --fast-list --transfers 16 \
          --log-file {2} --log-level INFO".format(backup_drives[service], service, \
          LOG_FILE.format(service))

    backup_process = subprocess.run(cmd, shell=True)

    if backup_process.returncode:
      backup_ran_with_errors = True

    return_codes[service] = backup_process.returncode
    outputs[service] = get_stats(service)
    attachments.append(create_attachment(service))

  if backup_ran_with_errors:
    elapsed_time = datetime.now() - start_time
    email_subject = "Backup Ran With Errors"

    email_msg = "An error occurred. Return codes: " + \
      ", ".join(["{0} ({1})".format(service, retcode) for (service, retcode) in return_codes.items()]) + \
      ". Please check the logs for more details."

    # Format the body of the email to show how much data was transferred
    outputs_text = "\n\n".join(["{0}:\n{1}".format(service, output) for (service, output) in outputs.items()])
    email_body = "{0}\n\nElapsed time: {1}\n\nOutputs:\n\n{2}".format(email_msg, elapsed_time, outputs_text)
    send_result_email(api_key, email_subject, email_body, attachments)

if __name__ == "__main__":
  api_key = parse_args()
  setup_logs()
  backup(api_key)
