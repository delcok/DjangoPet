# DjangoPet/__init__.py
# 确保 Django 启动时 Celery app 被加载,这样 @shared_task 装饰器才能注册到正确的 app
from .celery import app as celery_app

__all__ = ('celery_app',)