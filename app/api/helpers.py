"""Вспомогательные функции для API endpoints"""
from typing import Optional

from fastapi import HTTPException

from app.api.schemas import PublishResponse


def create_publish_response(
    success: bool,
    message: str,
    telegram_message_id: Optional[int] = None,
    post_id: Optional[int] = None
) -> PublishResponse:
    """Создает PublishResponse с заданными параметрами"""
    return PublishResponse(
        success=success,
        message=message,
        telegram_message_id=telegram_message_id,
        post_id=post_id
    )


def not_found_error(message: str = "Ресурс не найден") -> HTTPException:
    """Создает HTTPException для 404 ошибки"""
    return HTTPException(status_code=404, detail=message)


def bad_request_error(message: str) -> HTTPException:
    """Создает HTTPException для 400 ошибки"""
    return HTTPException(status_code=400, detail=message)


def server_error(message: str) -> HTTPException:
    """Создает HTTPException для 500 ошибки"""
    return HTTPException(status_code=500, detail=message)
