import os
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1.router import api_router
from app.core.config import get_settings

try:
    from app.core.exceptions import register_exception_handlers
except Exception:
    register_exception_handlers = None

try:
    from app.core.database import init_db
except Exception:
    init_db = None

try:
    from app.utils.logger import setup_logger
except Exception:
    setup_logger = None

settings = get_settings()
if setup_logger:
    setup_logger()
if init_db:
    init_db()

app = FastAPI(
    title=settings.app_name,
    description="AI 기반 소상공인 광고 콘텐츠 생성 백엔드 API",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
)

if register_exception_handlers:
    register_exception_handlers(app)

_DEFAULT_ORIGINS = "http://localhost:8501"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = str(uuid4())
    start_time = perf_counter()
    response = await call_next(request)
    elapsed_ms = round((perf_counter() - start_time) * 1000, 2)

    logger.info(
        "request_completed | request_id={} | method={} | path={} | status_code={} | elapsed_ms={}",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )

    response.headers["X-Request-ID"] = request_id
    return response

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.mount("/outputs", StaticFiles(directory=settings.output_dir), name="outputs")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "biz-ad-ai-backend",
        "status": "running",
        "docs": "/docs",
    }
