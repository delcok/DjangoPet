# -*- coding: utf-8 -*-
# @Time    : 2026/5/7 23:03
# @Author  : Delock

# -*- coding: utf-8 -*-
"""
促销活动 - Celery 定时任务

任务列表（在 Django Admin → Periodic Tasks 里配置调度）:
  campaigns.expire_coupons          每小时    标记已过期的用户券
  campaigns.end_expired_campaigns   每小时    自动结束已超时的活动
  campaigns.activate_due_campaigns  每分钟    自动上线到点的草稿活动
"""
import logging

from celery import shared_task
from django.utils import timezone

from .models import Campaign, UserCoupon

logger = logging.getLogger(__name__)


@shared_task(name='campaigns.expire_coupons')
def expire_coupons():
    """
    把 valid_to < now() 但状态还是 unused 的券批量置为 expired

    建议调度：每小时跑一次（serializer 层有兜底，1小时窗口期内的过期券
    用户也能看到正确状态，所以不用跑太勤）
    """
    now = timezone.now()
    updated = UserCoupon.objects.filter(
        status='unused',
        valid_to__isnull=False,
        valid_to__lt=now,
    ).update(status='expired')

    if updated > 0:
        logger.info(f'[expire_coupons] 已标记过期券 {updated} 张')
    return updated


@shared_task(name='campaigns.end_expired_campaigns')
def end_expired_campaigns():
    """
    自动结束已超过 end_time 的活动（active / paused 状态）

    建议调度：每小时跑一次
    """
    now = timezone.now()
    updated = Campaign.objects.filter(
        status__in=['active', 'paused'],
        end_time__lt=now,
    ).update(status='ended')

    if updated > 0:
        logger.info(f'[end_expired_campaigns] 自动结束活动 {updated} 个')
    return updated


@shared_task(name='campaigns.activate_due_campaigns')
def activate_due_campaigns():
    """
    自动上线到点的草稿活动
    （管理员预先把活动设为 draft + 设好开始时间，到点自动上线）

    建议调度：每分钟跑一次（让活动准时上线，最大延迟 1 分钟）
    """
    now = timezone.now()
    updated = Campaign.objects.filter(
        status='draft',
        start_time__lte=now,
        end_time__gt=now,
    ).update(status='active')

    if updated > 0:
        logger.info(f'[activate_due_campaigns] 自动上线活动 {updated} 个')
    return updated