"""Consistent process logging with noisy dependency suppression."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: int) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT)
    logging.getLogger("httpx").setLevel(logging.WARNING)
