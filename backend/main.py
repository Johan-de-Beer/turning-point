"""FastAPI entrypoint. Native loopback or private public-demo gateway backend."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .agents import MicrosoftProvider, MockProvider
from .generator import load_fixture
from .http_safety import DemoSafetyMiddleware
from .limits import ReplayLimits, integer
from .models import Control, EvidenceResponse, MatchMetadata, OverlayResponse, PreferencesPatch, RecapResponse, SessionCreate, SessionState, TacticalReport
from .replay import ReplayService, ServiceError
from .storage import Storage

BUILD_VERSION = "0.1.0"


def make_provider():
    provider = os.getenv("PROVIDER", "mock")
    if os.getenv("PUBLIC_DEMO", "false").lower() == "true" and provider != "mock":
        raise RuntimeError("The public demo requires PROVIDER=mock; external inference is disabled")
    if provider == "mock":
        return MockProvider(failure=os.getenv("MOCK_FAILURE", "none"))
    if provider == "microsoft":
        return MicrosoftProvider(endpoint=os.getenv("MICROSOFT_PROJECT_ENDPOINT", ""),
            model=os.getenv("MICROSOFT_MODEL_DEPLOYMENT", ""), approved=os.getenv("MICROSOFT_INFERENCE_APPROVED", "false").lower() == "true",
            max_calls=int(os.getenv("MICROSOFT_MAX_CALLS", "0")),
            max_output_tokens=int(os.getenv("MICROSOFT_MAX_OUTPUT_TOKENS", "1800")),
            timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "3")))
    raise RuntimeError("PROVIDER must be mock or microsoft")


def create_app(service: ReplayService | None = None, background_clock: bool = True) -> FastAPI:
    public = os.getenv("PUBLIC_DEMO", "false").lower() == "true"
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if service is None:
            match, fixture = load_fixture(correction=os.getenv("FIXTURE_CORRECTION", "0") == "1")
            limits = ReplayLimits.environment()
            storage = Storage(os.getenv("DATABASE_PATH", ".runtime/turning-point.sqlite3"), idle_seconds=limits.idle_seconds,
                idempotency_seconds=integer("IDEMPOTENCY_TTL_SECONDS", 3600 if public else 86_400, 60, 86_400),
                max_idempotency_entries=integer("MAX_IDEMPOTENCY_ENTRIES", 2048, 16, 4096),
                max_idempotency_per_scope=integer("MAX_IDEMPOTENCY_PER_SCOPE", 64, 8, 128))
            application.state.service = ReplayService(match, fixture, storage, provider=make_provider(),
                timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "3")), limits=limits)
        else:
            application.state.service = service
        if public and application.state.service.provider.name != "mock":
            raise RuntimeError("The public demo requires the mock provider")
        async def tick():
            ticks = 0
            while True:
                await asyncio.sleep(.1)
                active = application.state.service
                with active.lock:
                    for session in list(active.sessions.values()):
                        active.reconcile(session)
                    ticks += 1
                    if ticks % 100 == 0:
                        active.maintenance()
        ticker = asyncio.create_task(tick()) if background_clock else None
        # Build the synthetic tracking off the event loop so the first report is quick.
        warm = asyncio.create_task(asyncio.to_thread(application.state.service.tactics.prepared)) if service is None else None
        yield
        if warm:
            with contextlib.suppress(Exception):
                await warm
        if ticker:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
        await application.state.service.shutdown()
        if service is None:
            application.state.service.storage.close()

    application = FastAPI(title="Turning Point", version=BUILD_VERSION, lifespan=lifespan,
        description="Synthetic, observed-prefix-only replay. Mock roles are the default.",
        docs_url=None if public else "/docs", redoc_url=None if public else "/redoc", openapi_url=None if public else "/openapi.json")
    default_origins = "https://football.thedebeer.co.za" if public else "http://127.0.0.1:5173,http://localhost:5173"
    origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", default_origins).split(",") if origin.strip()]
    if any(origin == "*" for origin in origins):
        raise RuntimeError("ALLOWED_ORIGINS requires explicit origins")
    if public and (not origins or any(not origin.startswith("https://") for origin in origins)):
        raise RuntimeError("The public demo requires explicit HTTPS origins")
    application.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])

    application.add_middleware(DemoSafetyMiddleware, public=public, origins=origins)
    if public:
        hosts = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "football.thedebeer.co.za,localhost,127.0.0.1,backend").split(",") if host.strip()]
        if not hosts or any("*" in host for host in hosts):
            raise RuntimeError("The public demo requires explicit ALLOWED_HOSTS")
        application.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @application.exception_handler(ServiceError)
    async def service_error(_request, exc: ServiceError):
        return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message,
            "retryable": exc.retryable, "correlation_id": secrets.token_hex(8)})

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request, _exc):
        # Deliberately omit raw request values, capabilities and arbitrary input.
        return JSONResponse(status_code=422, content={"code": "invalid_request", "message": "Input does not satisfy contract v1.0",
            "retryable": False, "correlation_id": secrets.token_hex(8)})

    def active(request: Request) -> ReplayService:
        return request.app.state.service

    def capability(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise ServiceError("not_found", "Replay session was not found", 404)
        value = authorization[7:]
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value):
            raise ServiceError("not_found", "Replay session was not found", 404)
        return value

    def idempotency_key(key: str | None) -> str:
        if not key or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
            raise ServiceError("invalid_idempotency_key", "An unguessable Idempotency-Key is required", 422)
        return key

    def idempotent(service, scope, key, body, operation):
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        try:
            previous = service.storage.idempotent(scope, key, digest)
        except ValueError as exc:
            raise ServiceError("idempotency_conflict", str(exc)) from exc
        if previous is not None:
            return previous
        try:
            service.storage.check_idempotency_capacity(scope)
        except OverflowError as exc:
            raise ServiceError("request_history_limit", str(exc), 429, True) from exc
        result = operation().model_dump(mode="json")
        service.storage.save_idempotent(scope, key, digest, result)
        return result

    @application.get("/api/health")
    async def health():
        return {"status": "ok", "build_version": BUILD_VERSION, "schema_version": "1.0"}

    @application.get("/api/matches")
    async def matches(request: Request):
        return {"matches": [active(request).match.public().model_dump(mode="json")]}

    @application.post("/api/sessions", response_model=SessionState)
    async def sessions(body: SessionCreate, request: Request, authorization: str | None = Header(default=None),
                       key: str | None = Header(default=None, alias="Idempotency-Key")):
        service = active(request)
        cap, idem = capability(authorization), idempotency_key(key)
        with service.lock:
            return idempotent(service, "create:" + service.capability_hash(cap), idem, body.model_dump(),
                lambda: service.state(service.create(body, cap)))

    @application.get("/api/sessions/{session_id}/state", response_model=SessionState)
    async def state(session_id: str, request: Request, authorization: str | None = Header(default=None)):
        service = active(request)
        with service.lock:
            session = service.authorize(session_id, capability(authorization))
            return service.state(session)

    @application.get("/api/sessions/{session_id}/updates", response_model=SessionState)
    async def updates(session_id: str, request: Request, cursor: str | None = None,
                      authorization: str | None = Header(default=None)):
        if cursor and len(cursor) > 512:
            raise ServiceError("invalid_cursor", "Cursor exceeds local input limit", 422)
        service = active(request)
        with service.lock:
            session = service.authorize(session_id, capability(authorization))
            return service.state(session, cursor)

    @application.post("/api/sessions/{session_id}/controls", response_model=SessionState)
    async def controls(session_id: str, body: Control, request: Request,
                       authorization: str | None = Header(default=None), key: str | None = Header(default=None, alias="Idempotency-Key")):
        service = active(request)
        cap, idem = capability(authorization), idempotency_key(key)
        with service.lock:
            session = service.authorize(session_id, cap)
            def operation():
                service.controls(session, body)
                return service.state(session)
            return idempotent(service, f"control:{service.capability_hash(cap)}:{session_id}", idem, body.model_dump(), operation)

    @application.patch("/api/sessions/{session_id}/preferences", response_model=SessionState)
    async def preferences(session_id: str, body: PreferencesPatch, request: Request,
                          authorization: str | None = Header(default=None)):
        service = active(request)
        with service.lock:
            session = service.authorize(session_id, capability(authorization))
            service.preferences(session, body)
            return service.state(session)

    @application.get("/api/sessions/{session_id}/insights/{insight_id}/evidence", response_model=EvidenceResponse)
    async def evidence(session_id: str, insight_id: str, request: Request,
                       authorization: str | None = Header(default=None)):
        service = active(request)
        with service.lock:
            session = service.authorize(session_id, capability(authorization))
            return service.evidence(session, insight_id)

    @application.get("/api/sessions/{session_id}/recaps/{phase}", response_model=RecapResponse)
    async def recap(session_id: str, phase: Literal["half_time", "full_time"], request: Request,
                    authorization: str | None = Header(default=None)):
        service = active(request)
        with service.lock:
            session = service.authorize(session_id, capability(authorization))
            service.reconcile(session)
            return RecapResponse(session_id=session.session_id, generation=session.generation, data_epoch=session.data_epoch,
                playhead_ms=session.playhead_ms, next_cursor=service.cursor(session), recap=session.recaps[phase])

    @application.get("/api/sessions/{session_id}/tactics", response_model=TacticalReport)
    async def tactics(session_id: str, request: Request, authorization: str | None = Header(default=None)):
        service = active(request)
        with service.lock:
            session = service.authorize(session_id, capability(authorization))
            return service.tactics_report(session)

    @application.get("/api/sessions/{session_id}/overlay", response_model=OverlayResponse)
    async def overlay(session_id: str, request: Request, authorization: str | None = Header(default=None)):
        service = active(request)
        with service.lock:
            session = service.authorize(session_id, capability(authorization))
            service.reconcile(session)
            overlay = service.active_overlay(session)
            return OverlayResponse(session_id=session.session_id, generation=session.generation, data_epoch=session.data_epoch,
                playhead_ms=session.playhead_ms, next_cursor=service.cursor(session), status="active" if overlay else "empty", overlay=overlay)

    return application


app = create_app()
