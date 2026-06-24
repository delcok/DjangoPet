# -*- coding: utf-8 -*-
"""
DjangoPet — Celery 应用入口

启动 worker:
    celery -A DjangoPet worker -l info -Q default,dispatch,sms,adoption
启动 beat:
    celery -A DjangoPet beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'DjangoPet.settings')

app = Celery('DjangoPet', include=[
    'bill.tasks',
    'campaigns.tasks',
    'promotions.tasks',
    'adoption.tasks',
])

# 从 Django settings 加载 Celery 配置(以 CELERY_ 开头的项)
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自动发现各 app 下的 tasks.py
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    """调试用任务,确认 worker 工作正常"""
    print(f'Request: {self.request!r}')