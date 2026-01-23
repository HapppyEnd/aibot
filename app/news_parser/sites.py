import logging
from abc import ABC
from datetime import datetime
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

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
        """
        Выполняет HTTP-запрос с стандартными настройками

        Args:
            url: URL для запроса

        Returns:
            Response объект или None при ошибке
        """
        try:
            logger.debug(f"Выполнение запроса к {url}")
            response = requests.get(
                url,
                headers={'User-Agent': DEFAULT_USER_AGENT},
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            logger.debug(
                f"Успешный ответ от {url}, "
                f"статус: {response.status_code}"
            )
            return response
        except requests.exceptions.Timeout:
            logger.error(
                f"Таймаут при запросе к {url} "
                f"(>{REQUEST_TIMEOUT} сек)"
            )
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ошибка подключения к {url}: {e}")
            return None
        except requests.exceptions.HTTPError as e:
            status_code = (
                e.response.status_code
                if hasattr(e, 'response') and e.response
                else 'unknown'
            )
            logger.error(
                f"HTTP ошибка при запросе к {url}: {e} "
                f"(статус: {status_code})"
            )
            return None
        except requests.RequestException as e:
            logger.error(f"Ошибка при запросе к {url}: {e}")
            return None

    @staticmethod
    def _parse_datetime(datetime_str: str) -> datetime | None:
        """
        Парсит строку с датой в datetime объект

        Args:
            datetime_str: Строка с датой в ISO формате

        Returns:
            datetime объект или None при ошибке
        """
        if not datetime_str:
            return None

        try:
            datetime_str = datetime_str.replace('Z', '+00:00')
            dt = datetime.fromisoformat(datetime_str)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except (ValueError, AttributeError):
            return None


class HabrParser(SiteParser):
    def __init__(self):
        super().__init__('https://habr.com', 'ru/articles')
        self.source = 'habr'

    def parse(self):
        response = self._make_request(self._normalize_url())
        if not response:
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

                link_elem = h2.a
                article_url = link_elem.get('href')
                if article_url:
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

                datetime_str = time_elem.get('datetime')
                published_at = self._parse_datetime(datetime_str)
                if not published_at:
                    logger.warning(
                        f"Ошибка парсинга даты '{datetime_str}'"
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


class RSSParser(SiteParser):
    """
    Универсальный RSS парсер для любых сайтов с RSS-лентами

    Примеры использования:

    # Habr
    parser = RSSParser('https://habr.com/ru/rss/', 'habr_rss')

    # Лента.ру
    parser = RSSParser('https://lenta.ru/rss', 'lenta')

    # BBC News
    parser = RSSParser('https://feeds.bbci.co.uk/news/rss.xml', 'bbc')

    # Любой другой сайт с RSS
    parser = RSSParser('https://example.com/feed.xml', 'example')
    news = parser.parse()
    """

    def __init__(self, rss_url: str, source_name: str):
        """
        Инициализация RSS парсера

        Args:
            rss_url: URL RSS-ленты
                Примеры:
                - https://habr.com/ru/rss/
                - https://lenta.ru/rss
                - https://feeds.bbci.co.uk/news/rss.xml
            source_name: Имя источника (например, 'habr_rss', 'lenta', 'bbc')
        """
        super().__init__(rss_url, '')
        self.source = source_name

    def parse(self):
        """
        Парсит RSS-ленту и возвращает список новостей

        Returns:
            Список словарей с новостями
        """
        try:
            logger.info(f"Парсинг RSS: {self.base_url}")
            feed = feedparser.parse(self.base_url)

            if feed.bozo:
                logger.warning(
                    f"Ошибка парсинга RSS: {feed.bozo_exception}"
                )

            result = []
            for entry in feed.entries:
                try:
                    published_at = None
                    if (hasattr(entry, 'published_parsed') and
                            entry.published_parsed):
                        published_at = datetime(*entry.published_parsed[:6])
                    elif (hasattr(entry, 'updated_parsed') and
                          entry.updated_parsed):
                        published_at = datetime(*entry.updated_parsed[:6])
                    else:
                        published_at = datetime.now()

                    summary = ''
                    if hasattr(entry, 'summary'):
                        summary = entry.summary
                    elif hasattr(entry, 'description'):
                        summary = entry.description

                    if summary:
                        soup = BeautifulSoup(summary, 'html.parser')
                        summary = soup.get_text().strip()

                    url = None
                    if hasattr(entry, 'link'):
                        url = entry.link
                    elif hasattr(entry, 'links') and entry.links:
                        url = entry.links[0].get('href', '')

                    title = entry.title if hasattr(entry, 'title') else ''
                    result.append({
                        'title': title,
                        'url': url,
                        'summary': summary,
                        'source': self.source,
                        'published_at': published_at
                    })
                except Exception as e:
                    logger.warning(
                        f"Ошибка при обработке записи RSS: {e}",
                        exc_info=True
                    )
                    continue

            logger.info(
                f"RSS парсер '{self.source}' собрал {len(result)} новостей"
            )
            return result

        except Exception as e:
            logger.error(f"Ошибка при парсинге RSS {self.base_url}: {e}")
            return []


class UniversalHTMLParser(SiteParser):
    """
    Универсальный HTML парсер с настраиваемыми селекторами CSS
    Может работать с любыми сайтами, для которых указаны селекторы
    """

    def __init__(
        self,
        url: str,
        source_name: str,
        selectors: dict[str, str],
        articles_path: str = ''
    ):
        """
        Инициализация универсального HTML парсера

        Args:
            url: Базовый URL сайта
            source_name: Имя источника
            selectors: Словарь с CSS селекторами:
                - 'container': селектор контейнера со статьями
                  (например, 'article' или '.news-item')
                - 'title': селектор заголовка
                  (например, 'h2 a' или '.title')
                - 'url': селектор ссылки (например, 'a' или '.link').
                  Опционально
                - 'summary': селектор описания
                  (например, '.summary' или 'p'). Опционально
                - 'date': селектор даты (например, 'time' или '.date').
                  Опционально
            articles_path: Путь к странице со статьями
        """
        super().__init__(url, articles_path)
        self.source = source_name
        self.selectors = selectors

        if 'container' not in selectors or 'title' not in selectors:
            raise ValueError(
                "Необходимо указать селекторы 'container' и 'title'"
            )

    def _make_absolute_url(self, url: str) -> str:
        """Преобразует относительный URL в абсолютный"""
        if not url:
            return ''
        if url.startswith('http://') or url.startswith('https://'):
            return url
        if url.startswith('//'):
            return f"https:{url}"
        if url.startswith('/'):
            parsed = urlparse(self.base_url)
            return f"{parsed.scheme}://{parsed.netloc}{url}"
        return urljoin(self._normalize_url(), url)

    def _parse_date(self, date_elem) -> datetime | None:
        """Пытается распарсить дату из элемента"""
        if not date_elem:
            return None

        if hasattr(date_elem, 'get'):
            datetime_str = date_elem.get('datetime')
            if datetime_str:
                parsed = self._parse_datetime(datetime_str)
                if parsed:
                    return parsed

        if hasattr(date_elem, 'get_text'):
            date_text = date_elem.get_text().strip()
        else:
            date_text = str(date_elem).strip()
        if date_text:
            try:
                dt = date_parser.parse(date_text, fuzzy=True)
                return dt.replace(tzinfo=None) if dt.tzinfo else dt
            except (ValueError, TypeError):
                pass

        return None

    def parse(self):
        """Парсит HTML страницу по настроенным селекторам"""
        url = self._normalize_url()
        logger.debug(f"Парсинг HTML страницы: {url}")

        response = self._make_request(url)
        if not response:
            logger.warning(f"Не удалось получить ответ от {url}")
            return []

        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            logger.debug(
                f"HTML страница загружена, "
                f"размер: {len(response.text)} символов"
            )
        except Exception as e:
            logger.error(f"Ошибка при парсинге HTML с {url}: {e}")
            return []

        containers = soup.select(self.selectors['container'])
        logger.debug(
            f"Найдено {len(containers)} контейнеров "
            f"по селектору '{self.selectors['container']}'"
        )

        if not containers:
            logger.warning(
                f"Не найдены элементы по селектору "
                f"'{self.selectors['container']}' "
                f"на {self.base_url}. "
                f"Попробуйте настроить другие селекторы для этого сайта."
            )
            return []

        result = []
        for container in containers:
            try:
                title_elem = container.select_one(self.selectors['title'])
                if not title_elem:
                    continue

                title = title_elem.get_text().strip()
                if not title:
                    continue

                url = None
                if 'url' in self.selectors:
                    url_elem = container.select_one(self.selectors['url'])
                    if url_elem:
                        url = url_elem.get('href', '')
                elif title_elem.name == 'a':
                    url = title_elem.get('href', '')
                elif title_elem.parent and title_elem.parent.name == 'a':
                    url = title_elem.parent.get('href', '')

                if url:
                    url = self._make_absolute_url(url)

                summary = ''
                if 'summary' in self.selectors:
                    summary_elem = container.select_one(
                        self.selectors['summary']
                    )
                    if summary_elem:
                        summary = summary_elem.get_text().strip()

                published_at = None
                if 'date' in self.selectors:
                    date_elem = container.select_one(self.selectors['date'])
                    published_at = self._parse_date(date_elem)

                if not published_at:
                    published_at = datetime.now()

                result.append({
                    'title': title,
                    'url': url,
                    'summary': summary,
                    'source': self.source,
                    'published_at': published_at
                })
            except Exception as e:
                logger.warning(
                    f"Ошибка при парсинге элемента: {e}",
                    exc_info=True
                )
                continue

        logger.info(
            f"Универсальный парсер '{self.source}' собрал "
            f"{len(result)} новостей"
        )
        return result
