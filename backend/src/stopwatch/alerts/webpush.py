"""Web Push delivery (VAPID). No third-party push vendor: browsers' own push services, $0."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PushTarget:
    endpoint: str
    p256dh: str
    auth: str


def send_web_push(
    target: PushTarget, message: dict[str, Any], *, vapid_private_key: str, subject: str, ttl: int = 600
) -> str:
    """Returns "ok", "gone" (subscription expired: delete it) or "error:<status>"."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={"endpoint": target.endpoint, "keys": {"p256dh": target.p256dh, "auth": target.auth}},
            data=json.dumps(message),
            vapid_private_key=vapid_private_key,
            vapid_claims={"sub": subject},
            ttl=ttl,
            timeout=10,
        )
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            return "gone"
        return f"error:{status or 'unknown'}"
    return "ok"
