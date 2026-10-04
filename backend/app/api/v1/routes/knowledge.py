from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.knowledge_runtime import knowledge_capabilities
from app.db.models import User
from app.models.common import ApiResponse
from app.models.knowledge import (ChaptersPatch, ImportConfirmInput, ImportDraftPatch, ImportTaskInput,
                                  KnowledgeBaseInput, KnowledgeBasePatch, KnowledgeRequest, OriginalPracticeInput, TextDocumentInput)
from app.services.original_question_service import OriginalQuestionService
from app.services.knowledge_service import KnowledgeService

router = APIRouter(tags=["private-knowledge"])
CurrentUser = Annotated[User, Depends(get_current_user)]
Database = Annotated[AsyncSession, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("/knowledge-bases/capabilities", response_model=ApiResponse[dict])
async def capabilities(user: CurrentUser, config: Config):
    return ApiResponse(data=knowledge_capabilities(config))


@router.get("/knowledge-bases", response_model=ApiResponse[dict])
async def list_bases(user: CurrentUser, db: Database, config: Config, page: Page = 1, page_size: PageSize = 20):
    return ApiResponse(data=await KnowledgeService(db, config).list_bases(user, page, page_size))


@router.post("/knowledge-bases", response_model=ApiResponse[dict], status_code=201)
async def create_base(request: KnowledgeBaseInput, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).create_base(user, request))


@router.get("/knowledge-bases/{base_id}", response_model=ApiResponse[dict])
async def get_base(base_id: str, user: CurrentUser, db: Database, config: Config):
    service = KnowledgeService(db, config)
    return ApiResponse(data=await service.base_view(await service.base(user.id, base_id)))


@router.patch("/knowledge-bases/{base_id}", response_model=ApiResponse[dict])
async def patch_base(base_id: str, request: KnowledgeBasePatch, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).patch_base(user, base_id, request))


@router.delete("/knowledge-bases/{base_id}", response_model=ApiResponse[dict])
async def delete_base(base_id: str, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).delete_base(user, base_id))


@router.get("/knowledge-bases/{base_id}/documents", response_model=ApiResponse[dict])
async def list_documents(base_id: str, user: CurrentUser, db: Database, config: Config, page: Page = 1, page_size: PageSize = 20):
    return ApiResponse(data=await KnowledgeService(db, config).list_documents(user, base_id, page, page_size))


@router.post("/knowledge-bases/{base_id}/documents", response_model=ApiResponse[dict], status_code=202)
async def upload_document(base_id: str, user: CurrentUser, db: Database, config: Config,
                          request_id: Annotated[str, Form(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")],
                          file: Annotated[UploadFile, File()], filename: Annotated[str | None, Form(max_length=120)] = None):
    if filename is not None:
        file.filename = filename
    return ApiResponse(data=await KnowledgeService(db, config).upload_document(user, base_id, request_id, file))


@router.post("/knowledge-bases/{base_id}/text-documents", response_model=ApiResponse[dict], status_code=202)
async def text_document(base_id: str, request: TextDocumentInput, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).save_text(user, base_id, request))


@router.get("/knowledge-documents/{document_id}", response_model=ApiResponse[dict])
async def get_document(document_id: str, user: CurrentUser, db: Database, config: Config):
    service = KnowledgeService(db, config)
    return ApiResponse(data=await service.document_view(await service.document(user.id, document_id)))


@router.get("/knowledge-documents/{document_id}/preview", response_model=ApiResponse[dict])
async def preview_document(document_id: str, user: CurrentUser, db: Database, config: Config,
                           offset: Annotated[int, Query(ge=0, le=500000)] = 0,
                           limit: Annotated[int, Query(ge=1, le=10000)] = 4000):
    return ApiResponse(data=await KnowledgeService(db, config).preview(user, document_id, offset, limit))


@router.delete("/knowledge-documents/{document_id}", response_model=ApiResponse[dict])
async def delete_document(document_id: str, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).delete_document(user, document_id))


@router.patch("/knowledge-documents/{document_id}/chapters", response_model=ApiResponse[dict], status_code=202)
async def patch_chapters(document_id: str, request: ChaptersPatch, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).patch_chapters(user, document_id, request))


@router.get("/knowledge-processing-tasks/cleanup", response_model=ApiResponse[dict])
async def cleanup_tasks(user: CurrentUser, db: Database, config: Config, page: Page = 1,
                        page_size: PageSize = 20, base_id: str | None = None):
    return ApiResponse(data=await KnowledgeService(db, config).list_cleanup_tasks(user, base_id, page, page_size))


@router.get("/knowledge-processing-tasks/{task_id}", response_model=ApiResponse[dict])
async def processing_task(task_id: str, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).task_view(user, task_id))


@router.get("/knowledge-processing-tasks/by-request/{request_id}", response_model=ApiResponse[dict])
async def task_by_request(request_id: str, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).task_by_request(user, request_id))


@router.post("/knowledge-documents/{document_id}/processing-tasks", response_model=ApiResponse[dict], status_code=202)
async def retry_document(document_id: str, request: KnowledgeRequest, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).retry_document(user, document_id, request))


@router.post("/knowledge-processing-tasks/{task_id}/retry", response_model=ApiResponse[dict], status_code=202)
async def retry_task(task_id: str, request: KnowledgeRequest, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).retry_task(user, task_id, request))


@router.post("/knowledge-processing-tasks/{task_id}/cancel", response_model=ApiResponse[dict])
async def cancel_task(task_id: str, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await KnowledgeService(db, config).cancel_task(user, task_id))


@router.post("/knowledge-documents/{document_id}/question-import-tasks", response_model=ApiResponse[dict], status_code=202)
async def import_questions(document_id: str, request: ImportTaskInput, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await OriginalQuestionService(db, config).create_import(user, document_id, request))


@router.get("/question-imports/{draft_id}", response_model=ApiResponse[dict])
async def get_draft(draft_id: str, user: CurrentUser, db: Database, config: Config,
                    page: Page = 1, page_size: PageSize = 20, coverage_page: Page = 1):
    return ApiResponse(data=await OriginalQuestionService(db, config).draft_view(user, draft_id, page, page_size, coverage_page))


@router.patch("/question-imports/{draft_id}", response_model=ApiResponse[dict])
async def patch_draft(draft_id: str, request: ImportDraftPatch, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await OriginalQuestionService(db, config).patch_draft(user, draft_id, request))


@router.post("/question-imports/{draft_id}/confirm", response_model=ApiResponse[dict], status_code=201)
async def confirm_draft(draft_id: str, request: ImportConfirmInput, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await OriginalQuestionService(db, config).confirm(user, draft_id, request))


@router.get("/question-banks/{bank_id}", response_model=ApiResponse[dict])
async def get_bank(bank_id: str, user: CurrentUser, db: Database, config: Config,
                   chapter_ids: Annotated[list[str] | None, Query(max_length=1000)] = None):
    return ApiResponse(data=await OriginalQuestionService(db, config).bank_view(user, bank_id, chapter_ids))


@router.get("/knowledge-documents/{document_id}/question-banks", response_model=ApiResponse[dict])
async def list_banks(document_id: str, user: CurrentUser, db: Database, config: Config,
                     page: Page = 1, page_size: PageSize = 20):
    return ApiResponse(data=await OriginalQuestionService(db, config).list_banks(user, document_id, page, page_size))


@router.post("/question-banks/{bank_id}/practice-tasks", response_model=ApiResponse[dict], status_code=202)
async def practice_bank(bank_id: str, request: OriginalPracticeInput, user: CurrentUser, db: Database, config: Config):
    return ApiResponse(data=await OriginalQuestionService(db, config).create_practice(user, bank_id, request))
