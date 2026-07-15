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
from app.services.auth import (
    auth_mode,
    authenticate_request,
    configured_cors_origins,
    enforce_actor_rate_limit,
    permission_for_request,
    record_security_event,
    require_csrf,
    require_permission,
    validate_security_config,
)
from app.version import WORLDPULSE_VERSION


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_security_config()
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
    allow_origins=configured_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def local_session_guard(request: Request, call_next):
    if auth_mode() == "disabled" or request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    public = {"/api/health", "/api/version", "/api/v3/auth/login"}
    if path in public or not path.startswith("/api"):
        return await call_next(request)
    try:
        identity = authenticate_request(request)
        request.state.user = identity
        permission = permission_for_request(request.method, path)
        require_permission(identity, permission)
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            require_csrf(request)
            if permission == "run":
                enforce_actor_rate_limit("rate.run", identity.user_id, limit=30, window_seconds=60)
            elif permission == "rule_submit":
                enforce_actor_rate_limit("rate.rule_submit", identity.user_id, limit=10, window_seconds=60)
        response = await call_next(request)
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            record_security_event(
                "api.write", "allowed", actor_user_id=identity.user_id,
                resource_type=permission, resource_id=path, client_ip=request.client.host if request.client else None,
                detail={"method": request.method, "status_code": response.status_code},
            )
            if permission in {"run", "rule_submit"}:
                record_security_event(f"rate.{permission}", "counted", actor_user_id=identity.user_id, resource_id=path)
        return response
    except HTTPException as exc:
        actor = getattr(getattr(request, "state", None), "user", None)
        record_security_event(
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
