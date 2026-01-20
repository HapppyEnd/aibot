"""
Celery worker для запуска фоновых задач
"""
from app.tasks import celery_app

if __name__ == '__main__':
    celery_app.start()
