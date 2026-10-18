"""Generate a VAPID key pair for Web Push.

    uv run python -m stopwatch.alerts.vapid

Prints VAPID_PUBLIC_KEY (base64url uncompressed P-256 point, for the browser's applicationServerKey) and
VAPID_PRIVATE_KEY (base64url raw private scalar, accepted by pywebpush). Store the private key in SSM.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64(public_raw), _b64(private_raw)


if __name__ == "__main__":
    pub, priv = generate()
    print(f"VAPID_PUBLIC_KEY={pub}")
    print(f"VAPID_PRIVATE_KEY={priv}")
