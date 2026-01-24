from fastapi import HTTPException

from app.api.schemas import PublishResponse


def create_publish_response(
    success: bool,
    message: str,
    telegram_message_id: int | None = None,
    post_id: int | None = None
) -> PublishResponse:

    return PublishResponse(
        success=success,
        message=message,
        telegram_message_id=telegram_message_id,
        post_id=post_id
    )


def not_found_error(message: str = "Ресурс не найден") -> HTTPException:
    return HTTPException(status_code=404, detail=message)


def bad_request_error(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def server_error(message: str) -> HTTPException:
    return HTTPException(status_code=500, detail=message)
