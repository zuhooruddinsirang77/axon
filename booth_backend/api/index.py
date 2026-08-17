"""
Vercel entry point. Vercel's Python runtime auto-detects an ASGI/WSGI
variable named `app` in any file under /api and serves it as a serverless
function — the actual FastAPI app lives in ../service.py (named to avoid
Vercel's own entrypoint auto-detection, which would otherwise flag both
this file and main.py as ambiguous candidates). Runnable locally too via
`uvicorn service:app` from the booth_backend directory.
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service import app  # noqa: E402
