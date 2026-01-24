"""
Клиент для работы с SberGigaChat API
"""
import base64
import logging
import time

from gigachat import GigaChat
from gigachat.exceptions import ResponseError

from app.config import settings

logger = logging.getLogger(__name__)


class GigaChatError(Exception):
    """Базовый класс для ошибок GigaChat"""
    pass


class GigaChatClient:
    """Клиент для работы с SberGigaChat API"""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_key: str | None = None
    ):
        """
        Инициализация клиента GigaChat

        Args:
            client_id: Client ID для авторизации GigaChat
            client_secret: Client Secret для авторизации GigaChat
            api_key: API ключ авторизации GigaChat
        """
        self.client_id = client_id or settings.GIGACHAT_CLIENT_ID
        self.client_secret = client_secret or settings.GIGACHAT_CLIENT_SECRET
        self.api_key = api_key or settings.GIGACHAT_API_KEY

        has_client_creds = bool(self.client_id and self.client_secret)
        has_api_key = bool(self.api_key)

        if has_client_creds and has_api_key:
            logger.warning(
                "Указаны оба способа авторизации (client_id/client_secret "
                "и api_key). Используется api_key."
            )
            api_key_clean = self.api_key.strip()
            self.credentials = api_key_clean
            logger.debug("Используется готовый API ключ")
        elif has_client_creds:
            credentials_string = f"{self.client_id}:{self.client_secret}"
            self.credentials = base64.b64encode(
                credentials_string.encode('utf-8')
            ).decode('utf-8')
            logger.debug("Используются client_id и client_secret")
        elif has_api_key:
            api_key_clean = self.api_key.strip()
            self.credentials = api_key_clean
            logger.debug("Используется готовый API ключ")
        else:
            raise ValueError(
                "GigaChat credentials не найдены. "
                "Установите GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET "
                "или GIGACHAT_API_KEY в переменных окружения или .env. "
                "Получить можно на https://developers.sber.ru/studio"
            )

        self.max_retries = 3
        self.retry_delay = 2

    def generate_text(
        self,
        prompt: str,
        model: str = "GigaChat",
        max_tokens: int = 500,
        temperature: float = 0.7,
        retry_count: int = 0
    ) -> str:
        """
        Генерация текста через GigaChat API

        Args:
            prompt: Промпт для генерации
            model: Модель GigaChat (GigaChat, GigaChat-Pro и др.)
            max_tokens: Максимальное количество токенов
            temperature: Температура генерации (0.0-1.0)
            retry_count: Текущее количество попыток

        Returns:
            Сгенерированный текст
        """
        try:
            logger.info("Инициализация GigaChat с credentials...")
            logger.debug(
                f"Используем credentials (первые 20 символов): "
                f"{self.credentials[:20]}..."
            )

            with GigaChat(
                credentials=self.credentials,
                verify_ssl_certs=False,
                model=model,
                scope="GIGACHAT_API_PERS"
            ) as giga:
                logger.info("GigaChat инициализирован, отправка запроса...")
                response = giga.chat(prompt)
                generated_text = response.choices[0].message.content.strip()
                logger.info(
                    f"Успешно сгенерирован текст через GigaChat ({model})"
                )
                return generated_text

        except ResponseError as e:
            error_code = getattr(e, 'status_code', None)
            error_message = str(e)

            logger.error(
                f"Ошибка GigaChat SDK: код {error_code}, "
                f"сообщение: {error_message}"
            )

            if error_code == 400 and "decode" in error_message.lower():
                logger.error(
                    f"Ошибка авторизации GigaChat SDK (400): "
                    f"{error_message}"
                )
                raise GigaChatError(
                    f"Ошибка авторизации в GigaChat SDK (400): "
                    f"{error_message}. "
                    "Проверьте правильность GIGACHAT_API_KEY в .env. "
                    "Ключ должен быть в формате base64 "
                    "(client_id:client_secret). "
                    "Получите новый ключ на https://developers.sber.ru/studio"
                )

            if error_code == 401:
                logger.error(
                    f"Ошибка авторизации GigaChat (401): {error_message}"
                )
                raise GigaChatError(
                    "Ошибка авторизации (401): Неверный API ключ. "
                    "Проверьте правильность GIGACHAT_API_KEY в .env. "
                    "Получите новый ключ на https://developers.sber.ru/studio"
                )

            if error_code == 429 or "rate limit" in error_message.lower():
                logger.warning(f"Превышен лимит запросов GigaChat: {e}")
                if retry_count < self.max_retries:
                    wait_time = self.retry_delay * (2 ** retry_count)
                    logger.info(
                        f"Повторная попытка через {wait_time} секунд..."
                    )
                    time.sleep(wait_time)
                    return self.generate_text(
                        prompt, model, max_tokens, temperature, retry_count + 1
                    )
                raise GigaChatError(
                    f"Превышен лимит запросов GigaChat после "
                    f"{self.max_retries} попыток"
                )

            logger.error(f"Ошибка GigaChat API: {e}")
            raise GigaChatError(f"Ошибка GigaChat API: {str(e)}")

        except Exception as e:
            logger.error(f"Неожиданная ошибка при генерации текста: {e}")
            raise GigaChatError(f"Неожиданная ошибка: {str(e)}")
