"""Central logging setup."""

from __future__ import annotations

import logging

# HTTP client libraries log full request URLs (including query strings) at INFO.
_URL_LOGGING_LIBRARIES = ("httpx", "httpcore")


def configure_logging(level: str | int = "INFO") -> None:
    """Configure root logging and keep request URLs (which may carry credentials or user ids) out of the logs."""
    logging.basicConfig(level=level)
    for name in _URL_LOGGING_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)
