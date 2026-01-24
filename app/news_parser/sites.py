import logging
from abc import ABC
from datetime import datetime
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) '
    'Gecko/20100101 Firefox/146.0'
)
REQUEST_TIMEOUT = 10


class SiteParser(ABC):
    def __init__(self, url: str, articles_path: str = ''):
        self.base_url = url
        self.articles_path = articles_path

    def parse(self):
        raise NotImplementedError

    def _normalize_url(self, url: str = ''):
        base = self.base_url.rstrip('/')
        path = self.articles_path.strip('/') if self.articles_path else ''
        if not url:
            return f"{base}/{path}" if path else base
        url_part = url.lstrip('/')
        if path:
            return f"{base}/{path}/{url_part}"
        else:
            return f"{base}/{url_part}"

    def _make_request(self, url: str) -> requests.Response | None:
        """ HTTP-запрос. """
        try:
            response = requests.get(
                url,
                headers={'User-Agent': DEFAULT_USER_AGENT},
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            return response
        except requests.exceptions.Timeout:
            logger.error(f"Таймаут при запросе к {url}")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ошибка подключения к {url}: {e}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP ошибка {url}: {e}")
            return None
        except requests.RequestException as e:
            logger.error(f"Ошибка запроса к {url}: {e}")
            return None


class RSSParser(SiteParser):
    """
    RSS парсер.

    Примеры использования:
    ## Habr
    parser = RSSParser('https://habr.com/ru/rss/', 'habr_rss')
    ## Лента.ру
    parser = RSSParser('https://lenta.ru/rss', 'lenta')
    ## BBC News
    parser = RSSParser('https://feeds.bbci.co.uk/news/rss.xml', 'bbc')
    """

    def __init__(self, rss_url: str, source_name: str):
        super().__init__(rss_url, '')
        self.source = source_name

    def parse(self):
        """ Парсит RSS-ленту и возвращает список новостей. """
        try:
            feed = feedparser.parse(self.base_url)
            if feed.bozo:
                logger.warning(f"Ошибка парсинга RSS: {feed.bozo_exception}")

            result = []
            for entry in feed.entries:
                try:
                    if entry.published_parsed:
                        published_at = datetime(*entry.published_parsed[:6])
                    elif entry.updated_parsed:
                        published_at = datetime(*entry.updated_parsed[:6])
                    else:
                        published_at = datetime.now()

                    summary = getattr(entry, 'summary', '') or getattr(
                        entry, 'description', ''
                    )
                    if summary:
                        summary = BeautifulSoup(
                            summary, 'html.parser'
                        ).get_text().strip()

                    url = getattr(entry, 'link', None)
                    if not url and entry.links:
                        url = entry.links[0].get('href', '')

                    result.append({
                        'title': getattr(entry, 'title', ''),
                        'url': url,
                        'summary': summary,
                        'source': self.source,
                        'published_at': published_at
                    })
                except Exception as e:
                    logger.warning(f"Ошибка обработки: {e}")
                    continue

            logger.info(
                f"RSS парсер '{self.source}' собрал {len(result)} новостей")
            return result

        except Exception as e:
            logger.error(f"Ошибка парсинга RSS {self.base_url}: {e}")
            return []


class UniversalHTMLParser(SiteParser):
    """HTML парсер с настраиваемыми CSS селекторами."""

    def __init__(
        self,
        url: str,
        source_name: str,
        selectors: dict[str, str],
        articles_path: str = ''
    ):
        super().__init__(url, articles_path)
        self.source = source_name
        self.selectors = selectors

        if 'container' not in selectors or 'title' not in selectors:
            raise ValueError(
                "Необходимо указать селекторы 'container' и 'title'"
            )

    def _make_absolute_url(self, url: str) -> str:
        """Преобразует относительный URL в абсолютный."""
        if not url:
            return ''
        if url.startswith('//'):
            return f"https:{url}"
        return urljoin(self._normalize_url(), url)

    def _extract_item(self, container) -> dict | None:
        """Извлекает данные новости из контейнера."""
        title_elem = container.select_one(self.selectors['title'])
        if not title_elem:
            return None

        title = title_elem.get_text().strip()
        if not title:
            return None

        url = None
        if 'url' in self.selectors:
            url_elem = container.select_one(self.selectors['url'])
            url = url_elem.get('href', '') if url_elem else None
        elif title_elem.name == 'a':
            url = title_elem.get('href', '')
        elif title_elem.parent and title_elem.parent.name == 'a':
            url = title_elem.parent.get('href', '')
        url = self._make_absolute_url(url) if url else None

        summary_elem = container.select_one(
            self.selectors['summary']
        ) if 'summary' in self.selectors else None
        summary = summary_elem.get_text().strip() if summary_elem else ''

        return {
            'title': title,
            'url': url,
            'summary': summary,
            'source': self.source,
            'published_at': datetime.now()
        }

    def parse(self):
        """Парсит HTML страницу по настроенным селекторам"""
        url = self._normalize_url()
        response = self._make_request(url)
        if not response:
            return []

        try:
            soup = BeautifulSoup(response.text, 'html.parser')
        except Exception as e:
            logger.error(f"Ошибка парсинга HTML {url}: {e}")
            return []

        containers = soup.select(self.selectors['container'])
        if not containers:
            return []

        result = []
        for container in containers:
            try:
                item = self._extract_item(container)
                if item:
                    result.append(item)
            except Exception as e:
                logger.warning(f"Ошибка парсинга элемента: {e}")
                continue

        logger.info(f"Парсер '{self.source}' собрал {len(result)} новостей")
        return result
