"""AWS Lambda entry point: API Gateway HTTP API (payload v2) → Mangum → FastAPI.

Lifespan is off: the only startup work is building the app at import, which loads settings (and SSM
secrets) once per cold start.
"""

from __future__ import annotations

from mangum import Mangum

from .main import app

handler = Mangum(app, lifespan="off")
