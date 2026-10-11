import hashlib
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional
from urllib.parse import unquote

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from backend.config import PROJECT_ROOT, Settings
from backend.database import Database
from backend.protection import Protection
from backend.storage import Inbox
from backend.validation import InboxError


class SessionCreated(BaseModel):
    token: str
    status: str
    expires_at: datetime


class SessionStatus(BaseModel):
    status: str
    expires_at: datetime
    files: List[dict]
    customer_number: Optional[int] = None
    date: Optional[str] = None


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    config = settings if settings is not None else Settings()
    database = Database(config.database_path)
    inbox = Inbox(config, database)
    protection = Protection(config, database)

    async def maintenance():
        while True:
            await anyio.sleep(60)
            try:
                await run_in_threadpool(inbox.cleanup_expired)
            except (OSError, sqlite3.Error, RuntimeError):
                logging.getLogger(__name__).error("Inbox cleanup needs staff attention.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        protection.initialize()
        inbox.start()
        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(maintenance)
                try:
                    yield
                finally:
                    tasks.cancel_scope.cancel()
        finally:
            inbox.stop()

    # Only the three explicit UI files are served; inbox folders are never public.
    app = FastAPI(
        title="QR File Inbox",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(InboxError)
    async def inbox_error(request, error):
        return JSONResponse({"detail": error.message}, status_code=error.status_code)

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def storage_error(request, error):
        return JSONResponse(
            {"detail": "Depolama kullanılamıyor. Personelden yardım isteyin."}, status_code=503
        )

    def valid_token(token):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise InboxError(404, "Oturum bulunamadı veya süresi doldu.")

    @app.middleware("http")
    async def private_responses(request, call_next):
        try:
            if request.url.path.startswith("/api/") or request.url.path == "/healthz":
                await run_in_threadpool(protection.check_request, request)
            response = await call_next(request)
        except InboxError as error:
            response = await inbox_error(request, error)
        except (OSError, sqlite3.Error) as error:
            response = await storage_error(request, error)
        if response.status_code == 429:
            response.headers["Retry-After"] = "60"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Inbox-Service"] = "qr-print-inbox"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'none'"
        )
        return response

    @app.get("/")
    def customer_page():
        return FileResponse(PROJECT_ROOT / "web" / "index.html")

    @app.get("/style.css")
    def customer_style():
        return FileResponse(PROJECT_ROOT / "web" / "style.css", media_type="text/css")

    @app.get("/app.js")
    def customer_script():
        return FileResponse(PROJECT_ROOT / "web" / "app.js", media_type="text/javascript")

    @app.get("/api/v1/config")
    def customer_config():
        return {
            "max_file_size_mb": config.max_file_size_mb,
            "max_session_size_mb": config.max_session_size_mb,
            "max_files_per_session": config.max_files_per_session,
            "allowed_extensions": config.allowed_extensions.split(","),
        }

    @app.get("/healthz")
    def health():
        with database.connect() as connection:
            connection.execute("SELECT 1")
        return {"status": "ok"}

    @app.post("/api/v1/sessions", status_code=201, response_model=SessionCreated)
    def create_session():
        return database.create_session(config.session_ttl_minutes)

    @app.get("/api/v1/sessions/{token}/status", response_model=SessionStatus)
    def session_status(token: str):
        valid_token(token)
        session = database.get_session(token)
        if session is None:
            raise HTTPException(404, "Oturum bulunamadı veya süresi doldu.")
        return session

    @app.post("/api/v1/sessions/{token}/files", status_code=201)
    async def upload(token: str, request: Request):
        valid_token(token)
        # A raw body keeps limits enforceable while streaming, before multipart spooling.
        if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
            raise InboxError(415, "Dosyayı application/octet-stream olarak gönderin.")
        encoded_name = request.headers.get("x-file-name", "")
        if not encoded_name or len(encoded_name) > 2048:
            raise InboxError(422, "Geçerli bir dosya adı gerekli.")
        try:
            filename = unquote(encoded_name, errors="strict")
        except UnicodeError as error:
            raise InboxError(422, "Geçersiz dosya adı.") from error
        accepted = False
        with anyio.CancelScope(shield=True):
            reservation = await run_in_threadpool(inbox.reserve, token, filename)
        try:
            size = 0
            digest = hashlib.sha256()
            with anyio.fail_after(config.upload_timeout_seconds), \
                    reservation["part"].open("xb") as destination:
                async for chunk in request.stream():
                    await run_in_threadpool(protection.upload_bytes, len(chunk))
                    size += len(chunk)
                    if size > reservation["capacity"]:
                        raise InboxError(413, "Dosya veya oturum boyutu sınırı aşıldı.")
                    await run_in_threadpool(inbox.check_disk, len(chunk))
                    await run_in_threadpool(destination.write, chunk)
                    digest.update(chunk)
                await run_in_threadpool(destination.flush)
                await run_in_threadpool(os.fsync, destination.fileno())
            with anyio.CancelScope(shield=True):
                result = await run_in_threadpool(
                    inbox.accept, reservation, size, digest.hexdigest()
                )
                accepted = True
            return result
        except TimeoutError as error:
            raise InboxError(408, "Yükleme süresi doldu. Dosyayı yeniden seçin.") from error
        except ClientDisconnect as error:
            raise InboxError(
                400, "Yükleme bağlantısı kesildi; dosyayı yeniden gönderin."
            ) from error
        finally:
            if not accepted:
                with anyio.CancelScope(shield=True):
                    await run_in_threadpool(inbox.discard, reservation)

    @app.post("/api/v1/sessions/{token}/finalize")
    def finalize(token: str):
        valid_token(token)
        return inbox.finalize(token)

    return app
