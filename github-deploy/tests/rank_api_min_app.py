"""Minimal app mounting only the rank router (used for the local API test; the main thread mounts it in app/server.py)."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fastapi import FastAPI
from app.rank_api import router
app = FastAPI(); app.include_router(router)
