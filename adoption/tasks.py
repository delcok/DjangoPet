# -*- coding: utf-8 -*-
# @Time    : 2026/6/23 19:12
# @Author  : Delock

# -*- coding: utf-8 -*-
"""
adoption/tasks.py — 领养模块异步 & 定时任务

任务分两类:
  ① 即时通知: 由 serializer 内 transaction.on_commit → send_task 投递
     (通知渠道: 微信订阅消息/站内信/短信,按各自封装调用,此处只做数据组装+分发)
  ② celery beat 定时扫描: 过期交接 / 逾期打卡 / 限制到期自动解禁

celery beat 配置示例(settings.py 或 celery.py):
    CELERY_BEAT_SCHEDULE = {
        'adoption-scan-approve-expired': {
            'task': 'adoption.tasks.scan_approve_expired',
            'schedule': crontab(minute=0),                  # 每小时整点
        },
        'adoption-scan-overdue-updates': {
            'task': 'adoption.tasks.scan_overdue_updates',
            'schedule': crontab(hour=9, minute=0),          # 每天上午9点
        },
        'adoption-scan-restriction-lift': {
            'task': 'adoption.tasks.scan_restriction_lift',
            'schedule': crontab(hour=3, minute=0),          # 每天凌晨3点
        },
    }
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    AdopterProfile, AdoptionApplication, AdoptionUpdate,
    AdoptionUpdateTask, AdoptionViolation, ApplicationStatusLog, StrayPet,
)

logger = logging.getLogger(__name__)

# ---------- 业务常量 ----------
NO_SHOW_CREDIT_DEDUCT = 10          # 爽约扣信用分
OVERDUE_CREDIT_DEDUCT = 5           # 单期逾期扣分
CONSECUTIVE_OVERDUE_THRESHOLD = 2   # 连续 N 期逾期 → 自动违规 + 冻结
OVERDUE_RESTRICT_DAYS = 30          # 连续逾期自动限制天数


# ──────────────────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────────────────

def _log_status(application, from_status, to_status, operator=None, remark=''):
    ApplicationStatusLog.objects.create(
        application=application, from_status=from_status,
        to_status=to_status, operator=operator, remark=remark,
    )


def _send_wechat_subscribe_message(user_id, template_key, data):
    """
    微信订阅消息发送入口(按你们项目实际封装替换)。
    常见做法: 调 notification app 的统一接口,或直接调微信 API。
    此处仅占位 + 日志,实际对接时替换函数体即可。
    """
    # TODO: 对接你们的微信订阅消息 / 站内信通知模块
    # from notification.services import send_subscribe_msg
    # send_subscribe_msg(user_id=user_id, template=template_key, data=data)
    logger.info('[通知] user=%s template=%s data=%s', user_id, template_key, data)


# ══════════════════════════════════════════════════════════
#  一、即时通知任务(serializer on_commit 投递)
# ══════════════════════════════════════════════════════════

@shared_task(name='adoption.tasks.notify_new_application')
def notify_new_application(application_id):
    """新申请 → 通知管理员(后台待办 / 企微群机器人)"""
    try:
        app = (AdoptionApplication.objects
               .select_related('pet', 'applicant')
               .get(pk=application_id))
    except AdoptionApplication.DoesNotExist:
        logger.warning('notify_new_application: app %s 不存在', application_id)
        return

    logger.info('新领养申请 %s | 宠物: %s | 申请人: %s',
                app.application_no, app.pet.name, app.real_name)

    # TODO: 推送管理端(企微群机器人 / 后台消息中心)
    # 示例: webhook_notify(f'新领养申请 {app.application_no}: {app.real_name} 申请 {app.pet.name}')


@shared_task(name='adoption.tasks.notify_application_result')
def notify_application_result(application_id):
    """
    审核结果 → 通知申请人(微信订阅消息)
    覆盖: approved / rejected(含择优落选) / completed / returned / expired
    """
    try:
        app = (AdoptionApplication.objects
               .select_related('pet')
               .get(pk=application_id))
    except AdoptionApplication.DoesNotExist:
        logger.warning('notify_application_result: app %s 不存在', application_id)
        return

    status_msg = {
        'approved':  f'恭喜!您对 {app.pet.name} 的领养申请已通过,请在截止日前完成线下交接。',
        'rejected':  f'很抱歉,您对 {app.pet.name} 的领养申请未通过。原因: {app.reject_reason}',
        'completed': f'领养手续完成!{app.pet.name} 的新家之旅正式开始,请按计划打卡哦~',
        'returned':  f'{app.pet.name} 的领养记录已标记为退养,如有疑问请联系客服。',
        'expired':   f'您对 {app.pet.name} 的领养交接已超时,名额已释放。',
    }

    msg = status_msg.get(app.status)
    if not msg:
        logger.info('notify_application_result: app %s 状态 %s 无需通知',
                     application_id, app.status)
        return

    _send_wechat_subscribe_message(
        user_id=app.applicant_id,
        template_key='adoption_result',
        data={
            'application_no': app.application_no,
            'pet_name': app.pet.name,
            'status': app.get_status_display(),
            'message': msg,
        },
    )


@shared_task(name='adoption.tasks.notify_application_cancelled')
def notify_application_cancelled(application_id):
    """用户自助取消 → 通知管理员(如该宠物申请紧张可做运营干预)"""
    try:
        app = (AdoptionApplication.objects
               .select_related('pet')
               .get(pk=application_id))
    except AdoptionApplication.DoesNotExist:
        return

    logger.info('申请取消 %s | 宠物: %s 当前名额已释放',
                app.application_no, app.pet.name)
    # TODO: 推送管理端


@shared_task(name='adoption.tasks.notify_update_submitted')
def notify_update_submitted(update_id):
    """领养人提交打卡 → 通知管理员待查看"""
    try:
        update = (AdoptionUpdate.objects
                  .select_related('application__pet', 'task')
                  .get(pk=update_id))
    except AdoptionUpdate.DoesNotExist:
        return

    period = f'第{update.task.period_no}期' if update.task else '自主加更'
    logger.info('打卡提交 app=%s %s | 宠物: %s',
                update.application.application_no, period,
                update.application.pet.name)
    # TODO: 推送管理端待查看队列


@shared_task(name='adoption.tasks.alert_abnormal_update')
def alert_abnormal_update(update_id):
    """管理员标记动态异常 → 升级告警(紧急通知负责人 / 企微群)"""
    try:
        update = (AdoptionUpdate.objects
                  .select_related('application__pet', 'application__applicant')
                  .get(pk=update_id))
    except AdoptionUpdate.DoesNotExist:
        return

    logger.warning('⚠️ 领养动态异常 update=%s app=%s 宠物=%s 领养人=%s',
                   update.id, update.application.application_no,
                   update.application.pet.name, update.application.applicant_id)
    # TODO: 紧急告警(企微群机器人 @负责人 / 短信)


@shared_task(name='adoption.tasks.notify_violation')
def notify_violation(violation_id):
    """违规处罚 → 通知用户"""
    try:
        v = (AdoptionViolation.objects
             .select_related('application')
             .get(pk=violation_id))
    except AdoptionViolation.DoesNotExist:
        return

    _send_wechat_subscribe_message(
        user_id=v.user_id,
        template_key='adoption_violation',
        data={
            'violation_type': v.get_violation_type_display(),
            'penalty': v.get_penalty_display(),
            'description': v.description or v.get_violation_type_display(),
        },
    )


@shared_task(name='adoption.tasks.notify_update_reminder')
def notify_update_reminder(task_id):
    """打卡提醒(窗口开始 / 逾期催促)"""
    try:
        task = (AdoptionUpdateTask.objects
                .select_related('application__pet', 'application__applicant')
                .get(pk=task_id))
    except AdoptionUpdateTask.DoesNotExist:
        return

    _send_wechat_subscribe_message(
        user_id=task.application.applicant_id,
        template_key='adoption_update_reminder',
        data={
            'pet_name': task.application.pet.name,
            'period_no': task.period_no,
            'due_end': task.due_end.strftime('%Y-%m-%d'),
            'is_overdue': task.status == 'overdue',
        },
    )
    # 更新提醒记录,防重复推送
    AdoptionUpdateTask.objects.filter(pk=task.pk).update(
        reminded_at=timezone.now(),
        remind_count=F('remind_count') + 1,
    )


# ══════════════════════════════════════════════════════════
#  二、celery beat 定时扫描任务
# ══════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────
# 1) 每小时: approved 且超 approve_expire_at → expired
#    释放名额 + 记一次爽约违规
# ─────────────────────────────────────────────────────────

@shared_task(name='adoption.tasks.scan_approve_expired')
def scan_approve_expired():
    """审核通过但逾期未交接 → 自动过期,名额释放,记爽约"""
    now = timezone.now()
    expired_qs = AdoptionApplication.objects.filter(
        status='approved',
        approve_expire_at__lt=now,
    ).select_related('pet')

    count = 0
    for app in expired_qs:
        try:
            with transaction.atomic():
                locked_app = (AdoptionApplication.objects
                              .select_for_update()
                              .get(pk=app.pk))
                if locked_app.status != 'approved':
                    continue   # 已被其他进程处理

                pet = StrayPet.objects.select_for_update().get(pk=locked_app.pet_id)

                # ── 申请 → expired ──
                old_status = locked_app.status
                locked_app.status = 'expired'
                locked_app.save(update_fields=['status', 'updated_at'])
                _log_status(locked_app, old_status, 'expired',
                            remark='审核通过后逾期未交接,系统自动过期')

                # ── 释放宠物名额 ──
                pet.applying_count = max(pet.applying_count - 1, 0)
                # handover 状态说明只剩这一张通过的申请,过期后应回到 available
                if pet.status in ('handover', 'full'):
                    pet.status = 'available'
                pet.save(update_fields=['applying_count', 'status', 'updated_at'])

                # ── 爽约违规 ──
                profile, _ = (AdopterProfile.objects
                              .select_for_update()
                              .get_or_create(user_id=locked_app.applicant_id))
                AdoptionViolation.objects.create(
                    user_id=locked_app.applicant_id,
                    application=locked_app,
                    violation_type='no_show',
                    penalty='warning',
                    credit_deduct=NO_SHOW_CREDIT_DEDUCT,
                    description='审核通过后逾期未完成线下交接',
                    is_system=True,
                )
                profile.violation_count = F('violation_count') + 1
                profile.credit_score = max(0, profile.credit_score - NO_SHOW_CREDIT_DEDUCT)
                profile.save(update_fields=['violation_count', 'credit_score', 'updated_at'])

                count += 1

            # 事务成功后通知(用户 + 管理端)
            notify_application_result.delay(locked_app.id)

        except Exception:
            logger.exception('scan_approve_expired 处理失败 app_id=%s', app.id)

    if count:
        logger.info('scan_approve_expired: %s 张申请已过期', count)
    return count


# ─────────────────────────────────────────────────────────
# 2) 每天: pending 且过 due_end → overdue
#    推提醒;连续 N 期逾期 → 自动违规 + 冻结资格
# ─────────────────────────────────────────────────────────

@shared_task(name='adoption.tasks.scan_overdue_updates')
def scan_overdue_updates():
    """扫描逾期打卡,推提醒,连续逾期自动处罚"""
    now = timezone.now()

    # ── 第一步: pending 且已过截止 → overdue ──
    overdue_tasks = list(
        AdoptionUpdateTask.objects
        .filter(status='pending', due_end__lt=now)
        .select_related('application')
    )

    newly_overdue = 0
    for task in overdue_tasks:
        try:
            updated = (AdoptionUpdateTask.objects
                       .filter(pk=task.pk, status='pending')
                       .update(status='overdue', updated_at=now))
            if not updated:
                continue
            newly_overdue += 1

            # 推送逾期提醒
            notify_update_reminder.delay(task.pk)

            # ── 第二步: 检查是否连续 N 期逾期 ──
            _check_consecutive_overdue(task)

        except Exception:
            logger.exception('scan_overdue_updates 处理失败 task_id=%s', task.id)

    # ── 第三步: 已经 overdue 但还没提醒够的,再催一次(每天最多1次) ──
    stale_overdue = (
        AdoptionUpdateTask.objects
        .filter(status='overdue')
        .filter(  # 超过 24 小时没提醒过(或从未提醒)
            reminded_at__isnull=True,
        ) | AdoptionUpdateTask.objects.filter(
            status='overdue',
            reminded_at__lt=now - timedelta(days=1),
        )
    ).filter(remind_count__lt=3)  # 最多催 3 次

    reminded = 0
    for task in stale_overdue[:200]:  # 单次最多处理 200 条,防堆积拖垮
        try:
            notify_update_reminder.delay(task.pk)
            reminded += 1
        except Exception:
            logger.exception('逾期催促失败 task_id=%s', task.id)

    logger.info('scan_overdue_updates: 新逾期=%s, 催促=%s', newly_overdue, reminded)
    return newly_overdue


def _check_consecutive_overdue(task):
    """
    检查某个刚转 overdue 的任务所属申请是否已连续 N 期逾期。
    是 → 自动生成违规 + 冻结领养资格。
    幂等: 同一申请单只处理一次(靠查重 is_system + overdue_update 组合)。
    """
    app_id = task.application_id
    applicant_id = task.application.applicant_id

    # 查该申请单最近 N 期任务状态(按期数倒序)
    recent_tasks = list(
        AdoptionUpdateTask.objects
        .filter(application_id=app_id, period_no__lte=task.period_no)
        .order_by('-period_no')
        .values_list('status', flat=True)[:CONSECUTIVE_OVERDUE_THRESHOLD]
    )

    if len(recent_tasks) < CONSECUTIVE_OVERDUE_THRESHOLD:
        return
    if not all(s == 'overdue' for s in recent_tasks):
        return

    # 幂等: 该申请单已有系统自动生成的逾期违规则跳过
    already_exists = AdoptionViolation.objects.filter(
        application_id=app_id,
        violation_type='overdue_update',
        is_system=True,
    ).exists()
    if already_exists:
        return

    logger.warning('连续 %d 期逾期,自动处罚 applicant=%s app=%s',
                   CONSECUTIVE_OVERDUE_THRESHOLD, applicant_id, app_id)

    with transaction.atomic():
        profile, _ = (AdopterProfile.objects
                      .select_for_update()
                      .get_or_create(user_id=applicant_id))

        violation = AdoptionViolation.objects.create(
            user_id=applicant_id,
            application_id=app_id,
            violation_type='overdue_update',
            penalty='restrict',
            restrict_days=OVERDUE_RESTRICT_DAYS,
            credit_deduct=OVERDUE_CREDIT_DEDUCT,
            description=f'连续{CONSECUTIVE_OVERDUE_THRESHOLD}期未按时提交领养打卡',
            is_system=True,
        )

        profile.violation_count = F('violation_count') + 1
        profile.credit_score = max(0, profile.credit_score - OVERDUE_CREDIT_DEDUCT)
        until = timezone.now() + timedelta(days=OVERDUE_RESTRICT_DAYS)
        # 已有更晚的限制则保留更晚者;不把永久封禁降级
        if profile.status != 'banned':
            profile.status = 'restricted'
            if not (profile.restricted_until and profile.restricted_until > until):
                profile.restricted_until = until
        profile.save(update_fields=[
            'violation_count', 'credit_score',
            'status', 'restricted_until', 'updated_at',
        ])

    notify_violation.delay(violation.id)


# ─────────────────────────────────────────────────────────
# 3) 每天: restricted 且过 restricted_until → 恢复 normal
# ─────────────────────────────────────────────────────────

@shared_task(name='adoption.tasks.scan_restriction_lift')
def scan_restriction_lift():
    """限制到期自动解禁(与视图层惰性解禁互为双保险)"""
    now = timezone.now()
    count = (
        AdopterProfile.objects
        .filter(status='restricted', restricted_until__lt=now)
        .update(status='normal', restricted_until=None, updated_at=now)
    )
    if count:
        logger.info('scan_restriction_lift: %s 个用户已解禁', count)
    return count