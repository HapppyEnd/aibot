import logging
from typing import Dict

from telethon import TelegramClient

from app.config import settings

logger = logging.getLogger(__name__)

_auth_sessions: Dict[str, str] = {}


async def authorize_telegram(
    phone: str,
    code: str | None = None
) -> dict:
    """
    Авторизация в Telegram через API

    Args:
        phone: Номер телефона в формате +7XXXXXXXXXX
        code: Код подтверждения из Telegram
            (если None, отправляется запрос кода)

    Returns:
        Словарь с результатом авторизации:
        {
            'success': bool,
            'message': str,
            'phone': str | None,
            'username': str | None,
            'next_step': str | None
        }
    """
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        return {
            'success': False,
            'message': 'Telegram credentials not configured'
        }

    phone = phone.strip()

    session_name = getattr(
        settings, 'TELEGRAM_SESSION_NAME', 'telegram_session'
    )
    import os
    if os.path.exists('/app/telegram_sessions'):
        session_path = f'/app/telegram_sessions/{session_name}'
    else:
        session_path = session_name

    client = TelegramClient(
        session_path,
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH
    )

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            name = f'{me.first_name} {me.last_name or ""}'
            return {
                'success': True,
                'message': f'Уже авторизован как {name}',
                'phone': me.phone,
                'username': me.username
            }

        if not code:
            sent_code = await client.send_code_request(phone)
            _auth_sessions[phone] = sent_code.phone_code_hash
            return {
                'success': True,
                'message': 'Код подтверждения отправлен в Telegram',
                'next_step': 'code'
            }

        phone_code_hash = _auth_sessions.get(phone)
        if not phone_code_hash:
            return {
                'success': False,
                'message': (
                    'Сначала необходимо отправить запрос кода. '
                    'Вызовите API без параметра code.'
                ),
                'next_step': 'phone'
            }

        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        _auth_sessions.pop(phone, None)
        me = await client.get_me()
        name = f'{me.first_name} {me.last_name or ""}'
        return {
            'success': True,
            'message': f'Успешно авторизован как {name}',
            'phone': me.phone,
            'username': me.username
        }

    except Exception as e:
        logger.error(f'Ошибка при авторизации Telegram: {e}', exc_info=True)
        _auth_sessions.pop(phone, None)
        return {
            'success': False,
            'message': f'Ошибка авторизации: {str(e)}'
        }
    finally:
        await client.disconnect()
