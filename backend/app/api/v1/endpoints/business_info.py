"""
가게 정보 저장 API
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form
from loguru import logger

from app.core.deps import get_current_user
from app.core.user_repository import update_user_business_info
from app.schemas.common import success_response

router = APIRouter()


@router.post("/business-info")
async def save_business_info(
    store_name: str = Form(""),
    store_location: str = Form(""),
    current_user: dict = Depends(get_current_user),
):
    normalized_store_name = store_name.strip()
    normalized_store_location = store_location.strip()
    update_user_business_info(
        user_id=current_user["id"],
        store_name=normalized_store_name,
        store_location=normalized_store_location,
    )
    logger.info(
        "save_business_info | user_id={} | store_name={} | store_location={}",
        current_user["id"],
        normalized_store_name,
        normalized_store_location,
    )
    return success_response(
        data={
            "store_name": normalized_store_name,
            "store_location": normalized_store_location,
        }
    )
