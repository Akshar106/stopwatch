"""Per-route application rate limits (docs/04 §8.2). API Gateway throttles in front of these."""

from __future__ import annotations

from datetime import timedelta

from stopwatch.platform.ratelimit import RateLimit

_MINUTE = timedelta(minutes=1)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)

# Per client IP prefix
AUTH_LOGIN = RateLimit("auth_login", 10, _MINUTE)
AUTH_CALLBACK = RateLimit("auth_callback", 10, _MINUTE)
DEMO_CREATE = RateLimit("demo_create", 3, _HOUR)

# Per signed-in user
ME = RateLimit("me", 60, _MINUTE)
ME_EXPORT = RateLimit("me_export", 5, _DAY)
ME_DELETE = RateLimit("me_delete", 3, _DAY)
COMMUTES_READ = RateLimit("commutes_read", 60, _MINUTE)
COMMUTES_WRITE = RateLimit("commutes_write", 30, _MINUTE)
ALERTS_WRITE = RateLimit("alerts_write", 10, _MINUTE)
PUSH_WRITE = RateLimit("push_write", 10, _MINUTE)
ASK = RateLimit("ask", 20, _DAY)
