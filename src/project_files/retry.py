"""
Retry decorator for ATS API fetch methods.

Retries on HTTP 429, 500, 502, 503 with exponential backoff.
Does NOT retry on 404 (dead listing) or connection errors.
"""

import asyncio
import functools
from typing import Callable

import httpx
from loguru import logger


def with_retry(max_attempts: int = 3, base_delay: float = 1.0) -> Callable:
    """
    Async decorator factory.

    Retries the decorated coroutine on HTTP status 429, 500, 502, 503.
    Uses exponential backoff: base_delay * 2^attempt (1s → 2s → 4s by default).

    Does NOT retry on:
    - HTTP 404: dead listing — caller should return None
    - httpx.ConnectError / httpx.ConnectTimeout: network unreachable
    - Any other non-HTTP exception

    Usage:
        @with_retry(max_attempts=3, base_delay=1.0)
        async def fetch(self, ...) -> JobListing | None:
            ...
    """
    RETRYABLE_STATUSES = {429, 500, 502, 503}

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)

                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code

                    # 404 → dead listing; bubble up immediately, no retry
                    if status == 404:
                        raise

                    if status in RETRYABLE_STATUSES:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"[retry] HTTP {status} on attempt {attempt + 1}/{max_attempts}. "
                            f"Retrying in {delay:.1f}s — {func.__qualname__}"
                        )
                        last_exc = exc
                        await asyncio.sleep(delay)
                        continue

                    # Non-retryable HTTP error (e.g., 401, 403, 422) — raise immediately
                    raise

                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    # Network-level error — do not retry, bubble up
                    raise

                except httpx.TimeoutException as exc:
                    # Read/write timeout — retryable
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"[retry] Timeout on attempt {attempt + 1}/{max_attempts}. "
                        f"Retrying in {delay:.1f}s — {func.__qualname__}"
                    )
                    last_exc = exc
                    await asyncio.sleep(delay)
                    continue

            # All attempts exhausted
            if last_exc is not None:
                raise last_exc
            # Should never reach here, but satisfy the type checker
            raise RuntimeError(f"Retry loop exited unexpectedly in {func.__qualname__}")

        return wrapper

    return decorator
