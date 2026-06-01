# -*- coding: utf-8 -*-
"""
bill.services.dispatch — 自动派单 / 转单核心模块

外部入口
─────────────────────────────────────────────
  try_auto_dispatch(order_id)            # 单订单派单(walk_in/appointment/on_demand)
  offer_to_staff(order, staff)           # 派给指定员工(等待接单)
  fallback_to_manual(order, reason)      # 自动派单失败 → 转人工
  staff_accept(transfer_id, staff_id)    # 员工接受派单
  staff_reject(transfer_id, staff_id)    # 员工拒绝派单
  expire_pending_dispatches()            # 扫描超时(Celery beat)

  ★ 周期制(scheduled)专用 ★
  dispatch_delivery_schedule(schedule_id)    # 给某次配送指派员工
  dispatch_upcoming_deliveries(lookahead_days=2)  # 扫描即将到来的配送(Celery beat)

设计原则
─────────────────────────────────────────────
- service 配置字段全部从 dispatch_config / urgent_config dict 读取
- scheduled 类型的整单不参与 try_auto_dispatch,改由 DeliverySchedule 逐单派
- 所有外部入口加分布式锁,防止同源/多源并发
- 所有 DB 写入走 transaction.atomic + select_for_update
- 短信通过 Celery 异步发送,绝不影响主流程
- 派单失败永远降级到 PENDING_ASSIGNMENT 而非卡死
"""

import logging
import random
from datetime import time as _dtime, timedelta
from math import radians, sin, cos, sqrt, atan2

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 距离 / 时间冲突 / 并发数 工具
# ══════════════════════════════════════════════════════════════

def _haversine_distance_meters(lat1, lng1, lat2, lng2):
    """球面距离(米)。任一坐标缺失返回 None。"""
    if None in (lat1, lng1, lat2, lng2):
        return None
    try:
        lat1, lng1, lat2, lng2 = (
            radians(float(lat1)), radians(float(lng1)),
            radians(float(lat2)), radians(float(lng2)),
        )
    except (TypeError, ValueError):
        return None
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 6371000 * 2 * atan2(sqrt(a), sqrt(1 - a))


def _has_time_conflict_at(staff, date, start_time, end_time):
    """
    通用版:检查员工在指定日期+时段是否冲突。
    供 ServiceOrder 和 DeliverySchedule 共用。
    """
    from staffs.models import StaffTimeSlot

    if not (date and start_time and end_time):
        return False

    rest_dates = staff.rest_dates or []
    if date.isoformat() in rest_dates:
        return True

    weekday = str(date.isoweekday())
    schedule = (staff.work_schedule or {}).get(weekday, {})
    if schedule and schedule.get('is_work') is False:
        return True

    return StaffTimeSlot.objects.filter(
        staff=staff,
        date=date,
        status__in=[StaffTimeSlot.Status.BOOKED, StaffTimeSlot.Status.LOCKED],
        start_time__lt=end_time,
        end_time__gt=start_time,
    ).exists()


def _has_time_conflict(staff, order):
    """ServiceOrder 版本(向后兼容)"""
    return _has_time_conflict_at(
        staff, order.appointment_date,
        order.appointment_start, order.appointment_end,
    )


def _current_concurrent_count(staff):
    """估算员工当前并发订单数"""
    from bill.models import ServiceOrder, OrderTransfer, DeliverySchedule

    active = ServiceOrder.objects.filter(
        assigned_staff=staff,
        status__in=[
            ServiceOrder.Status.ASSIGNED,
            ServiceOrder.Status.IN_SERVICE,
        ],
    ).count()

    pending_offers = OrderTransfer.objects.filter(
        to_staff=staff,
        status=OrderTransfer.Status.PENDING,
        confirm_deadline__gt=timezone.now(),
    ).count()

    # 周期配送已分配 / 配送中的也算并发
    delivery_active = DeliverySchedule.objects.filter(
        assigned_staff=staff,
        scheduled_date=timezone.now().date(),
        status__in=[
            DeliverySchedule.Status.ASSIGNED,
            DeliverySchedule.Status.DELIVERING,
        ],
    ).count()

    return active + pending_offers + delivery_active


# ══════════════════════════════════════════════════════════════
# 服务配置读取(适配新的 dispatch_config dict 结构)
# ══════════════════════════════════════════════════════════════

def _read_dispatch_config(service):
    """
    从 service.dispatch_config dict 读派单参数,带默认值。
    没有 service 或无配置时返回安全默认。
    """
    cfg = (getattr(service, 'dispatch_config', None) if service else None) or {}
    return {
        'support_auto_dispatch': bool(cfg.get('support_auto_dispatch', True)),
        'accept_timeout_minutes': int(cfg.get('accept_timeout_minutes') or 5),
        'max_dispatch_attempts': int(cfg.get('max_dispatch_attempts') or 3),
    }


# ══════════════════════════════════════════════════════════════
# 候选员工算法(供 ServiceOrder 派单用)
# ══════════════════════════════════════════════════════════════

def find_candidates(order, exclude_ids=None, limit=10):
    """
    找出符合派单条件的员工列表。
    用于 walk_in / appointment / on_demand 类型订单。

    过滤:
      1. 商家匹配 + ACTIVE + 不待审核 + 允许接单
      2. work_status ∈ {ONLINE, BUSY}
      3. 紧急订单 → can_handle_urgent
      4. 服务能力(allow_choose_staff 取 staff_members,否则取 service_categories)
      5. 时间冲突
      6. 并发数 < max_concurrent_orders
      7. 距离(上门/取送)≤ service_radius

    排序:dispatch_weight 降序,同权重内随机
    """
    from staffs.models import Staff
    from services.models import Service

    exclude_ids = list(exclude_ids or [])

    qs = Staff.objects.filter(
        merchant_id=order.merchant_id,
        status=Staff.Status.ACTIVE,
        work_status__in=[Staff.WorkStatus.ONLINE, Staff.WorkStatus.BUSY],
        can_receive_transfer=True,
    ).exclude(
        verification_status=Staff.VerificationStatus.PENDING,
    )
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)
    if order.is_urgent:
        qs = qs.filter(can_handle_urgent=True)

    item = order.items.first()
    if item:
        try:
            service = Service.objects.get(id=item.service_id)
            if service.allow_choose_staff:
                staff_ids = list(service.staff_members.values_list('id', flat=True))
                if not staff_ids:
                    return []
                qs = qs.filter(id__in=staff_ids)
            elif service.category_id:
                qs = qs.filter(service_categories=service.category_id)
        except Service.DoesNotExist:
            pass

    candidates = list(qs.distinct())
    if not candidates:
        return []

    is_home_or_pickup = order.service_mode in ('home', 'pickup')
    filtered = []
    for staff in candidates:
        if _has_time_conflict(staff, order):
            continue
        if _current_concurrent_count(staff) >= staff.max_concurrent_orders:
            continue
        if is_home_or_pickup and order.receiver_lng and order.receiver_lat:
            dist = _haversine_distance_meters(
                staff.home_latitude, staff.home_longitude,
                order.receiver_lat, order.receiver_lng,
            )
            if dist is not None and dist > staff.service_radius:
                continue
        filtered.append(staff)

    if not filtered:
        return []

    random.shuffle(filtered)
    filtered.sort(key=lambda s: -(s.dispatch_weight or 0))
    return filtered[:limit]


# ══════════════════════════════════════════════════════════════
# 派单核心(walk_in / appointment / on_demand)
# ══════════════════════════════════════════════════════════════

def try_auto_dispatch(order_id):
    """
    自动派单入口(支付回调、Celery 重试、员工拒单后重派)。
    分布式锁保证同一订单同一时刻只有一个派单进程。

    ★ scheduled 类型订单不在此处理,直接跳过返回 None。
    """
    from utils.cache import DistributedLock

    lock = DistributedLock(f'auto_dispatch:{order_id}', expire=30)
    if not lock.acquire(blocking=False):
        logger.info('订单 %s 派单中,跳过本次重入', order_id)
        return None
    try:
        return _do_auto_dispatch(order_id)
    except Exception:
        logger.exception('try_auto_dispatch 失败 order_id=%s', order_id)
        return None
    finally:
        lock.release()


def _do_auto_dispatch(order_id):
    from bill.models import ServiceOrder
    from services.models import Service

    try:
        order = ServiceOrder.objects.get(id=order_id)
    except ServiceOrder.DoesNotExist:
        logger.warning('派单时订单不存在 order_id=%s', order_id)
        return None

    # ★ scheduled 类型:整单不参与派单,各 DeliverySchedule 独立派
    if order.service_type == 'scheduled':
        logger.debug('订单 %s 是周期制,跳过整单派单', order.order_no)
        return None

    if order.status not in (
        ServiceOrder.Status.PAID,
        ServiceOrder.Status.PENDING_ACCEPT,
        ServiceOrder.Status.PENDING_ASSIGNMENT,
    ):
        logger.debug('订单 %s 状态 %s 不可自动派单', order.order_no, order.status)
        return None

    service = None
    item = order.items.first()
    if item:
        try:
            service = Service.objects.get(id=item.service_id)
        except Service.DoesNotExist:
            pass

    cfg = _read_dispatch_config(service)

    if not cfg['support_auto_dispatch']:
        return fallback_to_manual(order, reason='服务未开启自动派单')

    if (order.dispatch_attempt_count or 0) >= cfg['max_dispatch_attempts']:
        return fallback_to_manual(
            order, reason=f'已尝试 {order.dispatch_attempt_count} 位员工均未接单',
        )

    attempted = list(order.attempted_staff_ids or [])
    candidates = find_candidates(order, exclude_ids=attempted, limit=1)
    if not candidates:
        return fallback_to_manual(order, reason='当前无可派候选员工')

    staff = candidates[0]
    return offer_to_staff(order, staff, timeout_minutes=cfg['accept_timeout_minutes'])


def offer_to_staff(order, staff, *, timeout_minutes=5):
    """
    把订单派给指定员工,等待对方接单。

      1) 取消订单上残留的 PENDING transfer
      2) 创建新 PENDING OrderTransfer
      3) 订单 status = PENDING_ACCEPT,设置 deadline
      4) attempted_staff_ids += staff.id, dispatch_attempt_count += 1
      5) 写日志,异步发短信
    """
    from bill.models import ServiceOrder, OrderTransfer

    now = timezone.now()
    deadline = now + timedelta(minutes=timeout_minutes)
    record_id = None

    with transaction.atomic():
        order = ServiceOrder.objects.select_for_update().get(pk=order.pk)

        if order.status not in (
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_ACCEPT,
            ServiceOrder.Status.PENDING_ASSIGNMENT,
            ServiceOrder.Status.ASSIGNED,
        ):
            logger.info('offer_to_staff 状态校验失败 order=%s status=%s',
                        order.order_no, order.status)
            return None

        # 清理残留 PENDING
        OrderTransfer.objects.filter(
            order=order, status=OrderTransfer.Status.PENDING,
        ).update(status=OrderTransfer.Status.CANCELLED)

        is_first = (order.assigned_staff_id is None)
        from_staff = order.assigned_staff
        sequence = OrderTransfer.objects.filter(order=order).count() + 1

        record = OrderTransfer.objects.create(
            order=order,
            from_staff=from_staff,
            to_staff=staff,
            initiated_by=OrderTransfer.InitiatedBy.SYSTEM,
            transfer_type=(
                OrderTransfer.TransferType.INITIAL if is_first
                else OrderTransfer.TransferType.VOLUNTARY
            ),
            reason='系统自动派单' if is_first else '系统自动重派',
            status=OrderTransfer.Status.PENDING,
            sequence=sequence,
            confirm_deadline=deadline,
        )
        record_id = record.id

        attempted = list(order.attempted_staff_ids or [])
        if staff.id not in attempted:
            attempted.append(staff.id)

        update_fields = [
            'status', 'dispatch_attempt_count',
            'attempted_staff_ids', 'pending_accept_deadline',
            'updated_at',
        ]
        order.status = ServiceOrder.Status.PENDING_ACCEPT
        order.dispatch_attempt_count = (order.dispatch_attempt_count or 0) + 1
        order.attempted_staff_ids = attempted
        order.pending_accept_deadline = deadline

        # 首次派单记录 dispatch_started_at(on_demand 时效统计用)
        if order.dispatch_started_at is None:
            order.dispatch_started_at = now
            update_fields.append('dispatch_started_at')

        order.save(update_fields=update_fields)

    _safe_log(
        order.order_no, 'service', 'assign',
        operator_type='system',
        description=f'系统派单 → {staff.name}(等待 {timeout_minutes} 分钟内接单)',
    )

    _enqueue_staff_pending_accept_sms(staff, order, deadline)

    logger.info('订单 %s 派给员工 %s deadline=%s',
                order.order_no, staff.id, deadline)
    return record_id


def fallback_to_manual(order, reason=''):
    """自动派单失败兜底:status → PENDING_ASSIGNMENT,通知商家"""
    from bill.models import ServiceOrder

    with transaction.atomic():
        order = ServiceOrder.objects.select_for_update().get(pk=order.pk)
        if order.status not in (
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_ACCEPT,
        ):
            return None

        order.status = ServiceOrder.Status.PENDING_ASSIGNMENT
        order.pending_accept_deadline = None
        order.save(update_fields=[
            'status', 'pending_accept_deadline', 'updated_at',
        ])

    _safe_log(
        order.order_no, 'service', 'system_auto',
        operator_type='system',
        description=f'自动派单失败转人工:{reason}',
    )
    _enqueue_merchant_no_staff_sms(order, reason)
    logger.warning('订单 %s 降级人工 reason=%s', order.order_no, reason)
    return order


# ══════════════════════════════════════════════════════════════
# 员工接单 / 拒单
# ══════════════════════════════════════════════════════════════

def staff_accept(transfer_id, staff_id):
    """员工接受派单。返回 (ServiceOrder, OrderTransfer)"""
    from bill.models import (
        ServiceOrder, OrderTransfer,
        _create_staff_time_slot, _cancel_staff_time_slot,
    )

    with transaction.atomic():
        try:
            record = (OrderTransfer.objects
                      .select_for_update()
                      .select_related('order', 'to_staff', 'from_staff')
                      .get(id=transfer_id))
        except OrderTransfer.DoesNotExist:
            raise ValueError('派单记录不存在')

        if record.to_staff_id != staff_id:
            raise ValueError('该派单非本人,不能接单')
        if record.status != OrderTransfer.Status.PENDING:
            raise ValueError(f'当前状态({record.get_status_display()})无法接单')
        if timezone.now() > record.confirm_deadline:
            record.status = OrderTransfer.Status.TIMEOUT
            record.save(update_fields=['status'])
            _trigger_redispatch(record.order_id)
            raise ValueError('该派单已超时')

        order = ServiceOrder.objects.select_for_update().get(pk=record.order_id)
        if order.status != ServiceOrder.Status.PENDING_ACCEPT:
            raise ValueError('订单状态已变更,无法接单')

        now = timezone.now()
        record.status = OrderTransfer.Status.CONFIRMED
        record.confirmed_at = now
        record.save(update_fields=['status', 'confirmed_at'])

        had_from_staff = bool(record.from_staff_id)

        if had_from_staff and record.from_staff_id != record.to_staff_id:
            _cancel_staff_time_slot(order, record.from_staff)

        order.assigned_staff = record.to_staff
        order.assigned_at = now
        order.status = ServiceOrder.Status.ASSIGNED
        order.pending_accept_deadline = None
        update_fields = [
            'assigned_staff', 'assigned_at', 'status',
            'pending_accept_deadline', 'updated_at',
        ]
        if had_from_staff:
            order.transfer_count = (order.transfer_count or 0) + 1
            update_fields.append('transfer_count')
        order.save(update_fields=update_fields)

        _create_staff_time_slot(order, record.to_staff)

    log_action = 'transfer_confirm' if had_from_staff else 'assign'
    _safe_log(
        order.order_no, 'service', log_action,
        operator_type='staff', operator_id=staff_id,
        description=f'员工 {record.to_staff.name} {"接受转单" if had_from_staff else "接单"}',
    )

    logger.info('订单 %s 被员工 %s 接单', order.order_no, record.to_staff.id)
    return order, record


def staff_reject(transfer_id, staff_id, reason=''):
    """员工拒单 → 取消该 transfer → 触发派下家"""
    from bill.models import ServiceOrder, OrderTransfer

    with transaction.atomic():
        try:
            record = (OrderTransfer.objects
                      .select_for_update()
                      .select_related('order')
                      .get(id=transfer_id))
        except OrderTransfer.DoesNotExist:
            raise ValueError('派单记录不存在')

        if record.to_staff_id != staff_id:
            raise ValueError('该派单非本人,不能拒绝')
        if record.status != OrderTransfer.Status.PENDING:
            raise ValueError('当前状态不可拒绝')

        record.status = OrderTransfer.Status.CANCELLED
        if reason:
            record.reason = (record.reason + ' | 员工拒绝: ' + reason)[:200]
        else:
            record.reason = (record.reason + ' | 员工拒绝')[:200]
        record.save(update_fields=['status', 'reason'])

        order = ServiceOrder.objects.select_for_update().get(id=record.order_id)
        if order.status == ServiceOrder.Status.PENDING_ACCEPT:
            order.pending_accept_deadline = None
            order.save(update_fields=['pending_accept_deadline', 'updated_at'])

    _safe_log(
        record.order.order_no, 'service', 'system_auto',
        operator_type='staff', operator_id=staff_id,
        description=f'员工拒单:{reason or "未填写原因"}',
    )

    _trigger_redispatch(record.order_id)
    return record


# ══════════════════════════════════════════════════════════════
# 超时清理(Celery beat 每 30 秒触发)
# ══════════════════════════════════════════════════════════════

def expire_pending_dispatches():
    """扫描所有超时未接单的 PENDING transfer:标记 TIMEOUT + 触发重派"""
    from bill.models import OrderTransfer

    now = timezone.now()
    pending_ids = list(
        OrderTransfer.objects.filter(
            status=OrderTransfer.Status.PENDING,
            confirm_deadline__lt=now,
        ).values_list('id', flat=True)[:500]
    )

    handled = 0
    affected_orders = set()
    for rec_id in pending_ids:
        try:
            with transaction.atomic():
                rec = OrderTransfer.objects.select_for_update().get(id=rec_id)
                if rec.status != OrderTransfer.Status.PENDING:
                    continue
                if rec.confirm_deadline > timezone.now():
                    continue
                rec.status = OrderTransfer.Status.TIMEOUT
                rec.save(update_fields=['status'])
                affected_orders.add(rec.order_id)
            handled += 1
        except Exception:
            logger.exception('处理超时派单失败 record_id=%s', rec_id)

    for order_id in affected_orders:
        _trigger_redispatch(order_id)

    if handled:
        logger.info('expire_pending_dispatches 处理超时 %s 条 / 影响订单 %s 个',
                    handled, len(affected_orders))
    return handled


# ══════════════════════════════════════════════════════════════
# ★ 周期制配送派单(scheduled 类型专用)
# ══════════════════════════════════════════════════════════════

def find_delivery_candidates(schedule, exclude_ids=None, limit=10):
    """
    给单次 DeliverySchedule 找候选配送员。
    与 find_candidates 类似,但日期/时间/地址来源于 schedule + 父订单。
    """
    from staffs.models import Staff
    from services.models import Service

    exclude_ids = list(exclude_ids or [])
    order = schedule.order

    qs = Staff.objects.filter(
        merchant_id=order.merchant_id,
        status=Staff.Status.ACTIVE,
        work_status__in=[Staff.WorkStatus.ONLINE, Staff.WorkStatus.BUSY],
        can_receive_transfer=True,
    ).exclude(
        verification_status=Staff.VerificationStatus.PENDING,
    )
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)

    item = order.items.first()
    if item:
        try:
            service = Service.objects.get(id=item.service_id)
            if service.allow_choose_staff:
                staff_ids = list(service.staff_members.values_list('id', flat=True))
                if not staff_ids:
                    return []
                qs = qs.filter(id__in=staff_ids)
            elif service.category_id:
                qs = qs.filter(service_categories=service.category_id)
        except Service.DoesNotExist:
            pass

    candidates = list(qs.distinct())
    if not candidates:
        return []

    filtered = []
    for staff in candidates:
        if _has_time_conflict_at(
            staff, schedule.scheduled_date,
            schedule.scheduled_window_start, schedule.scheduled_window_end,
        ):
            continue
        if _current_concurrent_count(staff) >= staff.max_concurrent_orders:
            continue
        # 距离过滤(周期制都是 home/pickup)
        if order.receiver_lng and order.receiver_lat:
            dist = _haversine_distance_meters(
                staff.home_latitude, staff.home_longitude,
                order.receiver_lat, order.receiver_lng,
            )
            if dist is not None and dist > staff.service_radius:
                continue
        filtered.append(staff)

    if not filtered:
        return []

    random.shuffle(filtered)
    filtered.sort(key=lambda s: -(s.dispatch_weight or 0))
    return filtered[:limit]


def dispatch_delivery_schedule(schedule_id):
    """
    给某次周期配送指派员工。

    简单流程(不走 PENDING_ACCEPT,直接 assign):
      1. 加锁
      2. 状态校验
      3. find_delivery_candidates(排除已尝试过的)
      4. 直接 assign 给第一位候选 → status=ASSIGNED
      5. 找不到 → 保持 PENDING 等下次扫描或商家手动处理

    返回:
      Staff 对象(派单成功)
      None  (无候选 / 已结束 / 加锁失败)
    """
    from utils.cache import DistributedLock
    from bill.models import DeliverySchedule

    lock = DistributedLock(f'delivery_dispatch:{schedule_id}', expire=30)
    if not lock.acquire(blocking=False):
        logger.info('配送 %s 派单中,跳过本次重入', schedule_id)
        return None

    try:
        with transaction.atomic():
            try:
                schedule = (DeliverySchedule.objects
                            .select_for_update()
                            .select_related('order')
                            .get(id=schedule_id))
            except DeliverySchedule.DoesNotExist:
                logger.warning('派单时配送记录不存在 schedule_id=%s', schedule_id)
                return None

            if schedule.status != DeliverySchedule.Status.PENDING:
                logger.debug('配送 %s 状态 %s 不可派单',
                             schedule_id, schedule.status)
                return None

            # 订阅暂停中,跳过
            if schedule.order.is_paused:
                logger.debug('订阅 %s 已暂停,跳过配送 %s 派单',
                             schedule.order.order_no, schedule_id)
                return None

            candidates = find_delivery_candidates(schedule, limit=1)
            if not candidates:
                logger.warning('配送 %s 无可用员工', schedule_id)
                _enqueue_merchant_no_staff_sms_for_delivery(schedule)
                return None

            staff = candidates[0]
            now = timezone.now()
            schedule.assigned_staff = staff
            schedule.assigned_at = now
            schedule.status = DeliverySchedule.Status.ASSIGNED
            schedule.save(update_fields=[
                'assigned_staff', 'assigned_at', 'status', 'updated_at',
            ])

        _safe_log(
            schedule.order.order_no, 'service', 'assign',
            operator_type='system',
            description=(
                f'周期配送第 {schedule.sequence} 次 '
                f'({schedule.scheduled_date}) → {staff.name}'
            ),
        )

        # 通知员工(异步)
        _enqueue_staff_delivery_assigned_sms(staff, schedule)

        logger.info('配送 %s 派给员工 %s', schedule_id, staff.id)
        return staff
    except Exception:
        logger.exception('dispatch_delivery_schedule 失败 schedule_id=%s', schedule_id)
        return None
    finally:
        lock.release()


def dispatch_upcoming_deliveries(lookahead_days=2):
    """
    周期任务:扫描即将到来的待派单配送,自动指派员工。
    由 Celery beat 每天/几小时触发一次。

    lookahead_days: 提前 N 天派单(默认 2 天)
    """
    from bill.models import DeliverySchedule

    today = timezone.now().date()
    deadline = today + timedelta(days=lookahead_days)

    pending_ids = list(
        DeliverySchedule.objects.filter(
            status=DeliverySchedule.Status.PENDING,
            scheduled_date__gte=today,
            scheduled_date__lte=deadline,
            order__is_paused=False,
            order__status__in=[
                # 父订单必须处于活跃订阅状态
                'paid', 'subscribing',
            ],
        ).values_list('id', flat=True)[:500]
    )

    if not pending_ids:
        return 0

    handled = 0
    for sid in pending_ids:
        if dispatch_delivery_schedule(sid):
            handled += 1

    logger.info(
        'dispatch_upcoming_deliveries 扫描 %s 条,派单成功 %s 条',
        len(pending_ids), handled,
    )
    return handled


# ══════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════

def _trigger_redispatch(order_id):
    """异步触发派下家(Celery)。"""
    try:
        from bill.tasks import task_try_auto_dispatch
        transaction.on_commit(
            lambda: task_try_auto_dispatch.delay(order_id)
        )
    except Exception:
        logger.exception('触发重派失败 order_id=%s', order_id)


def _safe_log(order_no, order_type, action, **kwargs):
    """写订单日志,失败仅记录"""
    try:
        from bill.serializers import create_order_log
        create_order_log(order_no, order_type, action, **kwargs)
    except Exception:
        logger.exception('订单日志写入失败 order_no=%s action=%s', order_no, action)


# ══════════════════════════════════════════════════════════════
# 短信通知(全部走 Celery 异步)
# ══════════════════════════════════════════════════════════════

def _enqueue_staff_pending_accept_sms(staff, order, deadline):
    """通知员工:有新订单待接单"""
    if not staff.phone:
        return
    try:
        from bill.tasks import task_send_sms
        minutes = max(1, int((deadline - timezone.now()).total_seconds() / 60))
        transaction.on_commit(lambda: task_send_sms.delay(
            phone=staff.phone,
            template_code='order_dispatch',
            template_param={
                'name': staff.name,
                'minutes': str(minutes),
            },
        ))
    except Exception:
        logger.exception('入队派单短信失败 staff_id=%s', staff.id)


def _enqueue_merchant_no_staff_sms(order, reason):
    """通知商家:自动派单失败,需人工介入"""
    try:
        from merchants.models import Merchant
        merchant = Merchant.objects.filter(id=order.merchant_id).first()
        if not merchant:
            return
        phone = (
            getattr(merchant, 'phone', '')
            or getattr(merchant, 'contact_phone', '')
        )
        if not phone:
            return
        from bill.tasks import task_send_sms
        transaction.on_commit(lambda: task_send_sms.delay(
            phone=phone,
            template_code='order_no_staff',
            template_param={'order': order.order_no[-8:]},
        ))
    except Exception:
        logger.exception('入队商家通知短信失败 order=%s', order.order_no)


def _enqueue_staff_delivery_assigned_sms(staff, schedule):
    """周期配送 ★ 通知员工:有新一次配送任务"""
    if not staff.phone:
        return
    try:
        from bill.tasks import task_send_sms
        transaction.on_commit(lambda: task_send_sms.delay(
            phone=staff.phone,
            template_code='delivery_assigned',
            template_param={
                'name': staff.name,
                'date': schedule.scheduled_date.isoformat(),
            },
        ))
    except Exception:
        logger.exception('入队配送派单短信失败 staff_id=%s', staff.id)


def _enqueue_merchant_no_staff_sms_for_delivery(schedule):
    """周期配送 ★ 通知商家:某次配送无可用员工"""
    try:
        from merchants.models import Merchant
        order = schedule.order
        merchant = Merchant.objects.filter(id=order.merchant_id).first()
        if not merchant:
            return
        phone = (
            getattr(merchant, 'phone', '')
            or getattr(merchant, 'contact_phone', '')
        )
        if not phone:
            return
        from bill.tasks import task_send_sms
        transaction.on_commit(lambda: task_send_sms.delay(
            phone=phone,
            template_code='delivery_no_staff',
            template_param={
                'order': order.order_no[-8:],
                'seq': str(schedule.sequence),
            },
        ))
    except Exception:
        logger.exception('入队商家配送通知短信失败 schedule=%s', schedule.id)