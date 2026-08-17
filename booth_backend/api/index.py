"""
Vercel entry point. Vercel's Python runtime auto-detects an ASGI/WSGI
variable named `app` in any file under /api and serves it as a serverless
function — the actual FastAPI app lives in ../main.py so it stays runnable
locally too (`uvicorn main:app`).
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402
