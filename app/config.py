"""All runtime settings, read from environment variables in one place.

Secrets (API keys) only ever come from the environment and are never logged or
sent to the browser. Every value has a safe default, and malformed numbers fall
back to the default rather than crashing or disabling a limit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Hosts this server answers to; protects against DNS-rebinding and
    # Host-header attacks. Set to your domain(s) when deploying.
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1")
    search_rate_limit_per_minute: int = 30

    # Optional upstream credentials / contact details (all free). The contact
    # email is sent to OpenAlex, Crossref and PubMed, which give faster, more
    # reliable service to callers who identify themselves.
    contact_email: str = ""
    openalex_api_key: str = ""
    s2_api_key: str = ""
    ncbi_api_key: str = ""
    core_api_key: str = ""   # CORE search is only enabled when this is set

    # Optional paid AI review.
    ai_review_enabled: bool = False
    ai_review_daily_limit: int = 200
    ai_review_per_minute: int = 6

    @classmethod
    def from_env(cls) -> "Settings":
        hosts = tuple(h.strip() for h in _str("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
                      if h.strip())
        return cls(
            allowed_hosts=hosts or cls.allowed_hosts,
            search_rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 30),
            # OPENALEX_EMAIL is the older name for the same setting.
            contact_email=_str("CONTACT_EMAIL") or _str("OPENALEX_EMAIL"),
            openalex_api_key=_str("OPENALEX_API_KEY"),
            s2_api_key=_str("S2_API_KEY"),
            ncbi_api_key=_str("NCBI_API_KEY"),
            core_api_key=_str("CORE_API_KEY"),
            # The Anthropic SDK reads the key itself; we only need to know it exists.
            ai_review_enabled=bool(_str("ANTHROPIC_API_KEY") or _str("ANTHROPIC_AUTH_TOKEN")),
            ai_review_daily_limit=_int("AI_REVIEW_DAILY_LIMIT", 200),
            ai_review_per_minute=_int("AI_REVIEW_PER_MINUTE", 6),
        )
