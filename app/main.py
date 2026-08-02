from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router
from app.api.v3 import router as v3_router
from app.api.v4 import router as v4_router
from app.api.v5 import router as v5_router
from app.api.v6 import router as v6_router
from app.api.v7 import router as v7_router
from app.api.v8 import router as v8_router
from app.api.v9 import router as v9_router
from app.api.v10 import router as v10_router
from app.api.v11 import router as v11_router
from app.services.identity import (
    IdentityApplicationPort,
    OrganizationApplicationPort,
    identity_service,
    organization_service,
)
from app.version import WORLDPULSE_VERSION


identity: IdentityApplicationPort = identity_service
organization_context: OrganizationApplicationPort = organization_service


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(_: FastAPI):
    identity.validate_security_config()
    yield


app = FastAPI(
    title="WorldPulse",
    description="全球多源综合风险指数与世界局势情景模拟器",
    version=WORLDPULSE_VERSION,
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=identity.configured_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def local_session_guard(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    public = {"/api/health", "/api/ready", "/api/version", "/api/v3/auth/login"}
    if path in public or not path.startswith("/api"):
        return await call_next(request)
    try:
        authentication_disabled = identity.auth_mode() == "disabled"
        actor = identity.ensure_system_user() if authentication_disabled else identity.authenticate_request(request)
        request.state.user = actor
        requested_organization = request.headers.get("x-worldpulse-org") or request.query_params.get("organization_id")
        organization = organization_context.current_organization(actor, requested_organization)
        request.state.organization_id = organization.organization_id
        organization_context.enforce_api_resource_scope(organization.organization_id, actor, request.method, path)
        if authentication_disabled:
            return await call_next(request)
        permission = identity.permission_for_request(request.method, path)
        identity.require_permission(actor, permission)
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            identity.require_csrf(request)
            if permission == "run":
                identity.enforce_actor_rate_limit("rate.run", actor.user_id, limit=30, window_seconds=60)
            elif permission == "rule_submit":
                identity.enforce_actor_rate_limit("rate.rule_submit", actor.user_id, limit=10, window_seconds=60)
            elif permission == "ingestion_write":
                identity.enforce_actor_rate_limit("rate.ingestion_write", actor.user_id, limit=20, window_seconds=60)
            elif permission == "monitoring_write":
                identity.enforce_actor_rate_limit("rate.monitoring_write", actor.user_id, limit=30, window_seconds=60)
        response = await call_next(request)
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            identity.record_security_event(
                "api.write", "allowed", actor_user_id=actor.user_id,
                resource_type=permission, resource_id=path, client_ip=request.client.host if request.client else None,
                detail={"method": request.method, "status_code": response.status_code},
            )
            if permission in {"run", "rule_submit", "monitoring_write"}:
                identity.record_security_event(f"rate.{permission}", "counted", actor_user_id=actor.user_id, resource_id=path)
        return response
    except HTTPException as exc:
        actor = getattr(getattr(request, "state", None), "user", None)
        identity.record_security_event(
            "api.access", "denied", actor_user_id=getattr(actor, "user_id", None),
            resource_id=path, client_ip=request.client.host if request.client else None,
            detail={"method": request.method, "status_code": exc.status_code},
        )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

app.mount("/static", StaticFiles(directory="app/static"), name="static")
studio_dist = Path("frontend/dist")
studio_assets = studio_dist / "assets"
if studio_assets.exists():
    app.mount("/studio/assets", StaticFiles(directory=studio_assets), name="studio_assets")
templates = Jinja2Templates(directory="app/templates")
app.include_router(router, prefix="/api")
app.include_router(v3_router, prefix="/api/v3")
app.include_router(v4_router, prefix="/api/v4")
app.include_router(v5_router, prefix="/api/v5")
app.include_router(v6_router, prefix="/api/v6")
app.include_router(v7_router, prefix="/api/v7")
app.include_router(v8_router, prefix="/api/v8")
app.include_router(v9_router, prefix="/api/v9")
app.include_router(v10_router, prefix="/api/v10")
app.include_router(v11_router, prefix="/api/v11")


@app.get("/favicon.ico")
def favicon() -> Response:
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#05070a"/><path d="M14 35c9-18 27-18 36 0" fill="none" stroke="#5ce1e6" stroke-width="5" stroke-linecap="round"/><circle cx="32" cy="34" r="8" fill="#f5b85f"/></svg>'
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/studio", response_class=HTMLResponse)
@app.get("/studio/{path:path}", response_class=HTMLResponse)
def studio(path: str = "") -> FileResponse:
    index = studio_dist / "index.html"
    if not index.exists():
        return FileResponse("app/templates/dashboard.html")
    return FileResponse(index)
