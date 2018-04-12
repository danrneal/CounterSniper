import logging
import requests
import sys
import os
import time

log = logging.getLogger('utils')


def get_path(path):
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    return path


def send_webhook(url, payload):
    resp = requests.post(url, json=payload, timeout=5)
    if resp.ok is not True:
        log.info("Discord response was {}".format(resp.json()))
        seconds = resp.json()['retry_after'] / 1000
        log.info("Trying again in {} seconds".format(seconds))
        time.sleep(seconds)
        raise requests.exceptions.RequestException(
            "Response received {}, webhook not accepted.".format(
                resp.status_code))


def try_sending(name, send_alert, args, max_attempts=3):
    for i in range(max_attempts):
        try:
            send_alert(**args)
            return
        except Exception as e:
            log.info((
                "Encountered error while sending notification ({}: {})"
            ).format(type(e).__name__, e))
            log.info((
                "{} is having connection issues. {} attempt of {}."
            ).format(name, i+1, max_attempts))
    log.info("Could not send notification... Giving up.")


class LoggerWriter:

    def __init__(self, level):
        self.level = level
        self.linebuf = ''

    def write(self, message):
        for line in message.rstrip().splitlines():
            self.level(line.rstrip())

    def flush(self):
        self.level(sys.stderr)
