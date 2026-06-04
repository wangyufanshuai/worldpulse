from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="WorldPulse",
    description="全球多源综合风险指数与世界局势情景模拟器",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
studio_dist = Path("frontend/dist")
studio_assets = studio_dist / "assets"
if studio_assets.exists():
    app.mount("/studio/assets", StaticFiles(directory=studio_assets), name="studio_assets")
templates = Jinja2Templates(directory="app/templates")
app.include_router(router, prefix="/api")


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
