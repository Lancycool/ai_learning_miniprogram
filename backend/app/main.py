from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from contextlib import asynccontextmanager

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.database import SessionLocal
from app.api.dependencies import get_quiz_generator, get_web_search_service
from app.services.quiz_task_service import QuizTaskWorker


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = QuizTaskWorker(SessionLocal, get_settings(), get_quiz_generator, get_web_search_service)
    worker.start()
    try:
        yield
    finally:
        await worker.close()


app = FastAPI(
    title="竹知岛 API",
    version="0.1.0",
    description="AI 闯关学习小程序 MVP 后端",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
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
