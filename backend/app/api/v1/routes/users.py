from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.core.exceptions import ContentRejectedError
from app.db.models import User
from app.models.common import ApiResponse
from app.models.user_system import UpdateProfileRequest, UserView
from app.services.auth_service import user_to_dict
from app.utils.content_filter import ContentFilter


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=ApiResponse[UserView])
async def me(user: Annotated[User, Depends(get_current_user)]) -> ApiResponse[UserView]:
    return ApiResponse(data=UserView.model_validate(user_to_dict(user)))


@router.patch("/me", response_model=ApiResponse[UserView])
async def update_me(request: UpdateProfileRequest, user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[UserView]:
    user.nickname = ContentFilter(get_settings().blocked_term_list).clean(request.nickname)
    user.profile_completed = True
    await db.commit()
    return ApiResponse(data=UserView.model_validate(user_to_dict(user)))


@router.post("/me/avatar", response_model=ApiResponse[UserView])
async def update_avatar(file: Annotated[UploadFile, File()], user: Annotated[User, Depends(get_current_user)], db: Annotated[AsyncSession, Depends(get_db)]) -> ApiResponse[UserView]:
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise ContentRejectedError("头像不能超过 5 MB")
    from io import BytesIO
    try:
        image = Image.open(BytesIO(content))
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError
        image.thumbnail((512, 512))
    except Exception as exc:
        raise ContentRejectedError("请选择 JPEG、PNG 或 WebP 图片") from exc
    directory = Path(get_settings().avatar_local_directory)
    if not directory.is_absolute():
        directory = Path(__file__).resolve().parents[4] / directory
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}.webp"
    image.convert("RGB").save(directory / name, "WEBP", quality=88)
    user.avatar_url = f"/avatars/{name}"
    user.profile_completed = True
    await db.commit()
    return ApiResponse(data=UserView.model_validate(user_to_dict(user)))
