from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from contextlib import asynccontextmanager
from starlette.concurrency import run_in_threadpool

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

async def _warm_up_hf_image_pipeline() -> None:
    from app.core.model_config import get_provider_name

    try:
        if get_provider_name("image_generation") != "hf":
            return
    except Exception:
        return

    try:
        from app.services.providers.factory import get_image_provider

        provider = get_image_provider()

        if hasattr(provider, "_load_text2img_pipeline"):
            logger.info("hf_image_pipeline_warmup_started")
            await run_in_threadpool(provider._load_text2img_pipeline)
            logger.info("hf_image_pipeline_warmup_completed")

    except Exception as exc:
        logger.exception("hf_image_pipeline_warmup_failed | error={}", str(exc))

async def _warm_up_food_classifier() -> None:
    try:
        from app.services.providers.food_classifier_provider import food_classifier_provider

        logger.info("food_classifier_warmup_started")
        await run_in_threadpool(food_classifier_provider._ensure_model_loaded)
        logger.info("food_classifier_warmup_completed")

    except Exception as exc:
        logger.exception("food_classifier_warmup_failed | error={}", str(exc))

async def _warm_up_poster_vlm() -> None:
    try:
        from app.utils.poster_vlm import is_poster_vlm_enabled, warm_up_poster_vlm

        if not is_poster_vlm_enabled():
            return

        logger.info("poster_vlm_warmup_started")
        await run_in_threadpool(warm_up_poster_vlm)
        logger.info("poster_vlm_warmup_completed")

    except Exception as exc:
        logger.exception("poster_vlm_warmup_failed | error={}", str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _warm_up_hf_image_pipeline()
    await _warm_up_poster_vlm()
    await _warm_up_food_classifier()
    yield

app = FastAPI(
    title=settings.app_name,
    description="AI 기반 소상공인 광고 콘텐츠 생성 백엔드 API",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

if register_exception_handlers:
    register_exception_handlers(app)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in settings.cors_allowed_origins.split(",")
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
