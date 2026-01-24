"""
Генератор постов с использованием AI (SberGigaChat)
"""
import logging

from app.ai.gigachat_client import GigaChatClient, GigaChatError
from app.ai.prompts import DEFAULT_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


class AIProviderError(Exception):
    """Базовый класс для ошибок AI провайдеров"""
    pass


class PostGenerator:
    """Генератор постов на основе новостей"""

    def __init__(self, api_key: str | None = None):
        """
        Инициализация генератора

        Args:
            api_key: API ключ GigaChat
        """
        self.client = GigaChatClient(api_key=api_key)
        self.default_prompt_template = DEFAULT_PROMPT_TEMPLATE
        logger.info("Используется SberGigaChat API")

    def generate_post(
        self,
        news_text: str,
        custom_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 500
    ) -> str:
        """
        Генерация поста на основе новости

        Args:
            news_text: Текст новости/сводка/пост из Telegram
            custom_prompt: Кастомный промпт
            model: Модель GigaChat (по умолчанию GigaChat)
            max_tokens: Максимальное количество токенов

        Returns:
            Сгенерированный текст поста

        Raises:
            AIProviderError: При ошибках генерации
        """
        if not news_text or not news_text.strip():
            raise ValueError("Текст новости не может быть пустым")

        if custom_prompt:
            prompt = custom_prompt.format(news_text=news_text)
        else:
            prompt = self.default_prompt_template.format(
                news_text=news_text
            )

        model = model or "GigaChat"

        logger.info("Начало генерации поста через SberGigaChat")
        try:
            generated_text = self.client.generate_text(
                prompt=prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=0.7
            )
            logger.info("Пост успешно сгенерирован")
            return generated_text

        except GigaChatError as e:
            logger.error(f"Ошибка при генерации поста: {e}")
            raise AIProviderError(f"Ошибка GigaChat: {str(e)}")
