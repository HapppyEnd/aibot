"""
Скрипт для тестирования публикации постов в Telegram-канал
"""
import asyncio
import logging

from app.config import settings
from app.telegram.publisher import TelegramPublisher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_publish():
    """Тестовая функция для публикации поста"""
    # Проверка наличия настроек
    if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
        logger.error(
            "TELEGRAM_API_ID и TELEGRAM_API_HASH должны быть "
            "установлены в .env файле"
        )
        return

    if not settings.TELEGRAM_CHANNEL_USERNAME:
        logger.error(
            "TELEGRAM_CHANNEL_USERNAME должен быть установлен в .env файле"
        )
        logger.info("Укажите username канала (например: @my_channel)")
        return

    # Создаем публикатор
    publisher = TelegramPublisher(
        api_id=settings.TELEGRAM_API_ID,
        api_hash=settings.TELEGRAM_API_HASH,
        channel_username=settings.TELEGRAM_CHANNEL_USERNAME
    )

    try:
        logger.info("Подключение к Telegram...")
        await publisher.connect()
        logger.info("Успешно подключено!")

        # Тестовый пост
        test_message = (
            "🤖 Тестовый пост от AI-генератора!\n\n"
            "Это проверка работы системы публикации."
        )

        logger.info(
            f"Публикация тестового поста в канал "
            f"{settings.TELEGRAM_CHANNEL_USERNAME}..."
        )
        success = await publisher.publish(test_message, post_id="test_001")
        if success:
            logger.info("✅ Пост успешно опубликован!")
        else:
            logger.warning("⚠️ Не удалось опубликовать пост")

    except Exception as e:
        logger.error(f"Ошибка: {e}")
    finally:
        await publisher.disconnect()
        logger.info("Отключено от Telegram")


if __name__ == "__main__":
    asyncio.run(test_publish())
