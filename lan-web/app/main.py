"""WSDoD LAN 2026 web service — app entry.

Run (dev):  uvicorn app.main:app --reload --port 8099
Behind nginx at /lan/ set LAN_WEB_ROOT_PATH=/lan."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .routes import auth_routes, public

app = FastAPI(title="WSDoD LAN 2026", root_path=settings.root_path)

# Session cookie carries the Discord identity + OAuth state. Secure-only in prod
# (TLS terminated at nginx); lax so the OAuth top-level redirect carries it back.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=settings.is_prod,
    same_site="lax",
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
    name="static",
)

app.include_router(public.router)
app.include_router(auth_routes.router)
