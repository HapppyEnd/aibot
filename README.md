# AI-генератор постов для Telegram

Сервис для автоматизации новостного Telegram-канала: парсинг новостей (RSS/сайты и Telegram-каналы), генерация постов через **Sber GigaChat**, публикация в канал через **Telethon**. 
---

## Возможности

- Парсинг новостей — RSS/сайты и публичные Telegram-каналы
- Очередь задач (Celery + Redis): парсинг → фильтрация → AI-генерация → публикация
- AI-генерация постов (GigaChat)
- Публикация в Telegram-канал через Telethon
- REST API — CRUD по источникам, ключевым словам, постам и новостям; ручная генерация и публикация
- Swagger: `/docs`

---

## Стек

FastAPI, PostgreSQL, SQLAlchemy 2 (async), Alembic, Celery, Redis, GigaChat, Telethon, feedparser, BeautifulSoup.

---

## Структура проекта

```
aibot/
├── app/
│   ├── main.py              # FastAPI, lifespan, логирование
│   ├── config.py            # Настройки (pydantic-settings)
│   ├── database.py          # Async SQLAlchemy, сессии
│   ├── models.py            # Source, Keyword, NewsItem, Post
│   ├── tasks.py             # Celery: парсинг, генерация, публикация
│   ├── utils.py             # Фильтрация, дубликаты
│   ├── ai/                  # GigaChat, генерация постов
│   ├── api/                 # REST-эндпоинты, schemas, helpers
│   ├── news_parser/         # Парсеры сайтов и Telegram-каналов
│   └── telegram/            # Telethon: auth, bot, publisher
├── alembic/                 # Миграции БД
├── docker-compose.yml       
├── Dockerfile
├── env.example
└── requirements.txt
```

---


**Требования:** Docker Engine 20.10+, Docker Compose v2.1+ (для `depends_on` с `condition: service_healthy`).

1. Скопируйте `env.example` в `.env` и заполните значения (всё необходимое — в примере).

2. Запустите сервисы:

   ```bash
   docker-compose up -d
   ```

   Миграции выполняются при старте API.

3. При первом использовании Telethon — авторизация через API:

   ```bash
   curl -X POST http://localhost:8000/api/telegram/auth -H "Content-Type: application/json" -d "{\"phone\": \"+79991234567\"}"
   curl -X POST http://localhost:8000/api/telegram/auth -H "Content-Type: application/json" -d "{\"phone\": \"+79991234567\", \"code\": \"12345\"}"
   ```


Документация API: **http://localhost:8000/docs**

---

Переменные окружения — см. `env.example`.

---

## API

Base URL: `http://localhost:8000`. Документация: **/docs**.

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/`, `/health` | Приветствие, проверка |
| GET/POST/PUT/DELETE | `/api/sources/` | CRUD источников |
| GET/POST/DELETE | `/api/keywords/` | CRUD ключевых слов |
| GET/POST/PUT/DELETE | `/api/posts/`, `/api/news/` | Посты и новости |
| POST | `/api/generate` | Сгенерировать пост (`news_id` или `text`) |
| POST | `/api/publish` | Опубликовать в канал (`post_id` или `text`) |
| POST | `/api/telegram/auth` | Авторизация Telethon |

### Примеры запросов

**Добавить источник (RSS):**

```bash
curl -X POST http://localhost:8000/api/sources/ \
  -H "Content-Type: application/json" \
  -d '{"type": "site", "name": "Habr", "url": "https://habr.com/ru/rss/all/", "enabled": true}'
```

**Добавить ключевое слово:**

```bash
curl -X POST http://localhost:8000/api/keywords/ \
  -H "Content-Type: application/json" \
  -d '{"word": "Python"}'
```

**Сгенерировать пост по тексту:**

```bash
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "В Python 3.12 вышли улучшения производительности интерпретатора."}'
```

**Опубликовать пост по ID:**

```bash
curl -X POST http://localhost:8000/api/publish \
  -H "Content-Type: application/json" \
  -d '{"post_id": 1}'
```

---

## Celery

- **Парсинг** (`parse_all_sources`) — по расписанию, обход источников, сохранение новостей.
- **Обработка** (`process_news_items`) — фильтрация → генерация → создание постов.
- **Публикация** — отдельные таски отправляют посты в канал.

Расписание в `app/tasks.py` (Celery Beat).

---
