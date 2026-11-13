#!/usr/bin/env python3
"""Optional logging.Handler that forwards records to Mezmo (formerly LogDNA)
over its HTTPS ingestion API. Enabled by setting LOGDNA_INGESTION_KEY in .env;
a no-op if that variable is unset, so it never affects nodes that don't use it.

Delivery failures are logged locally rather than raised, so a LogDNA/network
outage never blocks the uploader itself.
"""

import base64
import json
import logging
import os
import urllib.error
import urllib.request

INGEST_URL = "https://logs.mezmo.com/logs/ingest"
REQUEST_TIMEOUT = 5  # seconds


class LogDNAHandler(logging.Handler):
    def __init__(self, ingestion_key, hostname, app):
        super().__init__()
        self.hostname = hostname
        self.app = app
        auth = base64.b64encode(f"{ingestion_key}:".encode()).decode()
        self._headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Authorization": f"Basic {auth}",
        }
        self._fallback = logging.getLogger("logdna_handler")

    def emit(self, record):
        try:
            payload = json.dumps({
                "lines": [{
                    "line": self.format(record),
                    "app": self.app,
                    "level": record.levelname,
                    "timestamp": int(record.created * 1000),
                }]
            }).encode("utf-8")
            url = f"{INGEST_URL}?hostname={self.hostname}"
            req = urllib.request.Request(url, data=payload, headers=self._headers, method="POST")
            urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        except (urllib.error.URLError, OSError) as e:
            self._fallback.warning(f"LogDNA delivery failed: {e}")


def attach_logdna_handler(log, node_name, app, level=logging.WARNING):
    """Attach a LogDNA handler to `log` if LOGDNA_INGESTION_KEY is set in the
    environment. No-op otherwise. `level` controls the minimum severity
    forwarded — defaults to WARNING to avoid shipping routine per-segment
    debug chatter to a paid, rate-limited API.
    """
    key = os.environ.get("LOGDNA_INGESTION_KEY")
    if not key:
        return
    handler = LogDNAHandler(key, node_name, app)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter('%(module)s.%(funcName)s: %(message)s'))
    log.addHandler(handler)
    log.info("LogDNA logging enabled (level=%s)", logging.getLevelName(level))
