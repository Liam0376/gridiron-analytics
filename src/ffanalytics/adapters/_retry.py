"""Shared retry helpers for adapters. Centralizes the HTTP retry logic
that was previously duplicated across sleeper.py, statsguy.py, and
imported cross-module by weather.py and fantasypros.py."""

import time
import requests


def get_with_retry(http, url: str, timeout: int = 10, max_retries: int = 3) -> requests.Response:
    """HTTP GET with retry on 429/5xx. Returns the final response."""
    last_resp = None
    for attempt in range(max_retries):
        try:
            resp = http.get(url, timeout=timeout)
            last_resp = resp
            status = getattr(resp, "status_code", 200)
            if status == 429:
                retry_after_hdr = getattr(resp, "headers", {}).get("Retry-After") if hasattr(resp, "headers") else None
                retry_after = float(retry_after_hdr or (1.5 * (attempt + 1)))
                time.sleep(retry_after)
                continue
            if isinstance(status, int) and status >= 500 and attempt < max_retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout):
            if attempt == max_retries - 1:
                raise
            time.sleep(1.0 * (attempt + 1))
    if last_resp is not None:
        return last_resp
    raise requests.ConnectionError(f"all {max_retries} retries failed for {url}")


def call_with_retry(fn, max_retries: int = 3, backoff_base: float = 1.5):
    """Generic function-level retry with exponential backoff + jitter."""
    import random
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff_base * (attempt + 1) + random.uniform(0, 0.5))
