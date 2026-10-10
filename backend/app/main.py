from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager
import logging
from time import monotonic

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.database import SessionLocal
from app.core.knowledge_runtime import start_knowledge_worker
from app.api.dependencies import get_quiz_generator, get_web_search_service
from app.services.quiz_task_service import QuizTaskWorker
from app.core.observability import (
    METRICS,
    accepted_request_id,
    configure_logging,
    metric_path,
    record_http_request,
    request_id_context,
)


configure_logging(get_settings().observability_log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = QuizTaskWorker(SessionLocal, get_settings(), get_quiz_generator, get_web_search_service)
    worker.start()
    knowledge_worker = start_knowledge_worker(SessionLocal, get_settings())
    try:
        yield
    finally:
        if knowledge_worker is not None:
            try:
                await knowledge_worker.close()
            except Exception as exc:
                logging.getLogger(__name__).warning("knowledge_worker_close_failed type=%s", type(exc).__name__)
        await worker.close()


app = FastAPI(
    title="竹知岛 API",
    version="0.1.0",
    description="AI 闯关学习小程序 MVP 后端",
    lifespan=lifespan,
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = accepted_request_id(request.headers.get("X-Request-ID"))
    token = request_id_context.set(request_id)
    started = monotonic()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        logger.exception("http_request_failed", extra={"method": request.method, "path": request.url.path})
        raise
    finally:
        elapsed = monotonic() - started
        record_http_request(request.method, metric_path(request.url.path), status_code, elapsed)
        logger.info("http_request_finished", extra={"method": request.method, "path": request.url.path, "status_code": status_code, "duration_ms": round(elapsed * 1000, 2)})
        request_id_context.reset(token)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(METRICS.render(), media_type="text/plain; version=0.0.4; charset=utf-8")

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(v1_router)
avatar_dir = Path(__file__).resolve().parents[1] / "data" / "avatars"
app.mount("/avatars", StaticFiles(directory=avatar_dir, check_dir=False), name="avatars")


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.public_message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"code": 4001, "message": "请求参数不正确", "data": None},
    )
