"""
Vercel entry point. Vercel's Python runtime scans every .py file in the
project for a variable literally named `app` (not just specially-named
files), so the real FastAPI instance in ../service.py is named `booth_api`
instead — this is the ONLY file in the project exporting `app`, which is
what Vercel actually serves. Locally, run `uvicorn service:booth_api` from
the booth_backend directory instead of importing this file.
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service import booth_api as app  # noqa: E402
