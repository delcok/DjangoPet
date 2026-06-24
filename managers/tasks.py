# -*- coding: utf-8 -*-
# @Time    : 2026/6/24 15:06
# @Author  : Delock


from celery import shared_task
from celery.utils.log import get_task_logger

from managers.dashboard_stats import refresh_dashboard_cache

logger = get_task_logger(__name__)


@shared_task(time_limit=300, soft_time_limit=270)
def refresh_dashboard_task():
    """聚合管理端数据面板指标并写入 Redis(由 beat 每天调一次)。"""
    data = refresh_dashboard_cache()
    logger.info('数据面板已刷新 @ %s', data['generated_at'])
    return data['generated_at']