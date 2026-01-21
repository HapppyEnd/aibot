import logging
from abc import ABC
from datetime import datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class SiteParser(ABC):
    def __init__(self, url: str, articles_path: str = ''):
        self.base_url = url
        self.articles_path = articles_path

    def parse(self):
        raise NotImplementedError

    def _normalize_url(self, url: str = ''):
        # Убираем лишние слэши и формируем правильный URL
        base = self.base_url.rstrip('/')
        path = self.articles_path.strip('/') if self.articles_path else ''

        if not url:
            # Возвращаем базовый URL с путем к статьям
            return f"{base}/{path}" if path else base

        url_part = url.lstrip('/')
        if path:
            return f"{base}/{path}/{url_part}"
        else:
            return f"{base}/{url_part}"


class HabrParser(SiteParser):
    def __init__(self):
        super().__init__('https://habr.com', 'ru/articles')
        self.source = 'habr'

    def parse(self):
        try:
            user_agent = (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) '
                'Gecko/20100101 Firefox/146.0'
            )
            response = requests.get(
                self._normalize_url(),
                headers={'User-Agent': user_agent},
                timeout=10
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Ошибка при запросе к Habr: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')

        articles_list = soup.find('div', class_='tm-articles-list')
        if not articles_list:
            logger.warning("Не найдена секция со статьями на Habr")
            return []

        result = []
        for article in articles_list.find_all('article'):
            try:
                h2 = article.find('h2')
                if not h2 or not h2.a:
                    continue

                # Получаем ссылку на статью
                link_elem = h2.a
                article_url = link_elem.get('href')
                if article_url:
                    # Если относительный URL, делаем абсолютным
                    if article_url.startswith('/'):
                        article_url = self.base_url + article_url
                    elif not article_url.startswith('http'):
                        article_url = self._normalize_url(article_url)

                title_elem = h2.a.find('span')
                if not title_elem:
                    title_elem = h2.a

                title = title_elem.text.strip() if title_elem else None
                if not title:
                    continue

                # Пытаемся получить summary из разных возможных мест
                summary = ''
                summary_elem = (
                    article.find('div', class_='tm-article-snippet') or
                    article.find('div', class_='article-formatted-body') or
                    article.find('div', class_='tm-article-body')
                )
                if summary_elem:
                    summary = summary_elem.text.strip()

                time_elem = article.find('time')
                if not time_elem or not time_elem.get('datetime'):
                    continue

                # Обрабатываем дату с возможными разными форматами
                datetime_str = time_elem.get('datetime')
                try:
                    # Убираем Z и обрабатываем как ISO формат
                    datetime_str = datetime_str.replace('Z', '+00:00')
                    published_at = datetime.fromisoformat(datetime_str)
                    # Если дата с timezone, убираем timezone
                    if published_at.tzinfo is not None:
                        published_at = published_at.replace(tzinfo=None)
                except (ValueError, AttributeError) as e:
                    logger.warning(
                        f"Ошибка парсинга даты '{datetime_str}': {e}"
                    )
                    continue

                result.append({
                    'title': title,
                    'url': article_url or None,
                    'summary': summary,
                    'source': self.source,
                    'published_at': published_at
                })
            except Exception as e:
                logger.warning(
                    f"Ошибка при парсинге статьи: {e}",
                    exc_info=True
                )
                continue

        logger.info(f"Парсер Habr собрал {len(result)} новостей")
        return result
