"""
Telegram бот для управления и мониторинга
"""
from telethon import TelegramClient


class TelegramBot:
    """Базовый класс для работы с Telegram"""

    def __init__(self, api_id: int, api_hash: str):
        self.client = TelegramClient('telegram_bot_session', api_id, api_hash)

    async def start(self):
        """Запустить бота"""
        await self.client.start()

    async def stop(self):
        """Остановить бота"""
        await self.client.disconnect()
