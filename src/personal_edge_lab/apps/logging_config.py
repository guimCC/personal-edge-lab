"""Consistent process logging with noisy dependency suppression."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: int) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)
    for logger_name in (
        "google.auth",
        "google_auth_oauthlib",
        "httpcore",
        "httpx",
        "requests",
        "urllib3",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
