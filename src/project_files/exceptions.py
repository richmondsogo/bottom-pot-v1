"""
Custom exception hierarchy for Bottom Pot.

Every provider catches its own exceptions internally and logs at WARNING level.
The orchestrator and API layer must never crash because a single provider failed.
"""


class BottomPotError(Exception):
    """Base class for all Bottom Pot exceptions."""
    pass


class SearchProviderError(BottomPotError):
    """Raised when an ATS API returns a non-recoverable HTTP error."""

    def __init__(self, provider: str, status_code: int, message: str) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] HTTP {status_code}: {message}")


class RateLimitError(BottomPotError):
    """Raised when a provider returns HTTP 429."""

    def __init__(self, provider: str, retry_after: int | None = None) -> None:
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(f"[{provider}] Rate limited. Retry after: {retry_after}s")


class BotBlockError(BottomPotError):
    """Raised when a Nigerian scraper detects a CAPTCHA or bot-block page."""

    def __init__(self, site: str) -> None:
        self.site = site
        super().__init__(f"[{site}] Bot block or CAPTCHA detected")


class ParseError(BottomPotError):
    """Raised when response parsing fails unexpectedly."""

    def __init__(self, ats: str, url: str, detail: str) -> None:
        super().__init__(f"[{ats}] Parse failed at {url}: {detail}")
