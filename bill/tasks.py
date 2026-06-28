# -*- coding: utf-8 -*-
# bill/tasks.py
"""
bill 模块的 Celery 任务

任务清单
─────────────────────────────────────────────
事件触发型(由业务代码 .delay() 调用):
    task_try_auto_dispatch(order_id)        # 单订单派单
    task_send_sms(...)                      # 短信异步发送

周期型(由 Celery Beat 调度,需在 admin 配 PeriodicTask):
    task_expire_pending_dispatches()        # 30 秒 / 次:扫超时派单
    task_dispatch_upcoming_deliveries()     # 15 分钟 / 次:批量派周期配送
    task_activate_due_subscriptions()       # 每天 02:00:订阅到期日激活

调用方
─────────────────────────────────────────────
- 支付回调(pay/views.py):     transaction.on_commit + task_try_auto_dispatch.delay
- 员工拒单 / 派单超时:          dispatch._trigger_redispatch
- 排班资源短信通知:             dispatch._enqueue_*_sms
- 周期 beat:                   后三个周期任务
"""

import logging

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# 1. 单订单派单(事件触发)
# ════════════════════════════════════════════════════════════════

@shared_task(
    bind=True,
    name='bill.tasks.task_try_auto_dispatch',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def task_try_auto_dispatch(self, order_id):
    """
    尝试给订单派单(支付回调 / 员工拒单 / 派单超时后重派)。

    重试策略:
      - 异常自动重试,指数退避,最大 60 秒,最多 3 次
      - 业务返回 None(找不到候选员工等)不算异常,不会触发重试
    """
    from bill.services.dispatch import try_auto_dispatch

    try:
        result = try_auto_dispatch(order_id)
        if result is not None:
            logger.info(
                'task_try_auto_dispatch ok order_id=%s record=%s',
                order_id, getattr(result, 'id', result),
            )
        return {
            'order_id': order_id,
            'result': str(result) if result else None,
        }
    except SoftTimeLimitExceeded:
        logger.error('task_try_auto_dispatch 软超时 order_id=%s', order_id)
        raise
    except Exception:
        logger.exception('task_try_auto_dispatch 异常 order_id=%s', order_id)
        raise


# ════════════════════════════════════════════════════════════════
# 2. 短信异步发送(事件触发)
# ════════════════════════════════════════════════════════════════

@shared_task(
    name='bill.tasks.task_send_sms',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=2,
    soft_time_limit=15,
    time_limit=20,
)
def task_send_sms(phone, template_code, template_param):
    """
    异步发短信(派单通知 / 商家人工介入提醒 / 接单确认通知用户等)。
    短信失败不阻塞业务流程,只在 worker 端记日志。
    """
    if not phone:
        logger.warning('task_send_sms 跳过:phone 为空 template=%s', template_code)
        return False
    try:
        from utils.send_sms import get_sms_service
        ok, msg = get_sms_service().send_notification(
            phone=phone,
            template_code=template_code,
            template_param=template_param or {},
        )
        if not ok:
            logger.warning(
                'task_send_sms 失败 phone=%s template=%s msg=%s',
                phone, template_code, msg,
            )
        return ok
    except SoftTimeLimitExceeded:
        logger.error('task_send_sms 软超时 phone=%s', phone)
        raise
    except Exception:
        logger.exception('task_send_sms 异常 phone=%s', phone)
        raise


# ════════════════════════════════════════════════════════════════
# 3. 周期任务:扫描派单超时(由 Beat 每 30 秒触发)
# ════════════════════════════════════════════════════════════════

@shared_task(
    name='bill.tasks.task_expire_pending_dispatches',
    soft_time_limit=45,
    time_limit=55,
)
def task_expire_pending_dispatches():
    """
    扫描所有超过 confirm_deadline 仍 PENDING 的 OrderTransfer,
    标记为 TIMEOUT 并异步触发 task_try_auto_dispatch 派下家。
    """
    from bill.services.dispatch import expire_pending_dispatches

    try:
        n = expire_pending_dispatches()
        if n > 0:
            logger.info('task_expire_pending_dispatches 处理 %s 条超时', n)
        return n
    except SoftTimeLimitExceeded:
        logger.error('task_expire_pending_dispatches 软超时')
        return -1
    except Exception:
        logger.exception('task_expire_pending_dispatches 异常')
        return -1


# ════════════════════════════════════════════════════════════════
# 4. 周期任务:周期配送提前派单(由 Beat 每 15 分钟触发)
# ════════════════════════════════════════════════════════════════

@shared_task(
    name='bill.tasks.task_dispatch_upcoming_deliveries',
    soft_time_limit=120,
    time_limit=150,
)
def task_dispatch_upcoming_deliveries():
    """
    扫描 lookahead_days=2 天内的待派单 DeliverySchedule,
    为每条找一个配送员并直接 ASSIGN(不走 PENDING_ACCEPT)。
    用于 scheduled 类型订单的批量预派。
    """
    from bill.services.dispatch import dispatch_upcoming_deliveries

    try:
        return dispatch_upcoming_deliveries(lookahead_days=2)
    except SoftTimeLimitExceeded:
        logger.error('task_dispatch_upcoming_deliveries 软超时')
        return -1
    except Exception:
        logger.exception('task_dispatch_upcoming_deliveries 异常')
        return -1


# ════════════════════════════════════════════════════════════════
# 5. 周期任务:订阅起始日激活(由 Beat 每天 02:00 触发)
# ════════════════════════════════════════════════════════════════

@shared_task(
    name='bill.tasks.task_activate_due_subscriptions',
    soft_time_limit=60,
)
def task_activate_due_subscriptions():
    """
    把今天该开始配送但仍处于 PAID 状态的 scheduled 订单
    批量推进到 SUBSCRIBING(订阅活跃期)。

    被暂停的订阅(is_paused=True)不动。
    """
    from django.utils import timezone
    from bill.models import ServiceOrder

    today = timezone.localdate()
    try:
        n = ServiceOrder.objects.filter(
            service_type='scheduled',
            status=ServiceOrder.Status.PAID,
            subscription_start_date__lte=today,
            is_paused=False,
        ).update(status=ServiceOrder.Status.SUBSCRIBING)
        if n:
            logger.info('task_activate_due_subscriptions 激活订阅 %s 个', n)
        return n
    except SoftTimeLimitExceeded:
        logger.error('task_activate_due_subscriptions 软超时')
        return -1
    except Exception:
        logger.exception('task_activate_due_subscriptions 异常')
        return -1



@shared_task(
    name='bill.tasks.task_cancel_stale_pending_orders',
    soft_time_limit=120,
)
def task_cancel_stale_pending_orders():
    """
    取消超过 30 分钟未支付的订单,释放资源:
      - 时段(服务订单)
      - 优惠券
      - 库存(如果支持)
    """
    from datetime import timedelta
    from django.utils import timezone
    from bill.models import ServiceOrder, ProductOrder
    from bill.views import _release_time_slot
    from bill.serializers import return_coupon

    cutoff = timezone.now() - timedelta(minutes=30)
    cancelled = 0

    # 服务订单
    stale_svc = ServiceOrder.objects.filter(
        status=ServiceOrder.Status.PENDING_PAYMENT,
        created_at__lt=cutoff,
    )[:200]
    for order in stale_svc:
        try:
            order.status = ServiceOrder.Status.CANCELLED
            order.cancel_reason = '超时未支付自动取消'
            order.save(update_fields=['status', 'cancel_reason', 'updated_at'])
            _release_time_slot(order)
            return_coupon(order)
            cancelled += 1
        except Exception:
            logger.exception('取消超时服务订单失败 order_no=%s', order.order_no)

    # 商品订单
    stale_prod = ProductOrder.objects.filter(
        status=ProductOrder.Status.PENDING_PAYMENT,
        created_at__lt=cutoff,
    )[:200]
    for order in stale_prod:
        try:
            order.status = ProductOrder.Status.CANCELLED
            order.cancel_reason = '超时未支付自动取消'
            order.save(update_fields=['status', 'cancel_reason', 'updated_at'])
            return_coupon(order)
            cancelled += 1
        except Exception:
            logger.exception('取消超时商品订单失败 order_no=%s', order.order_no)

    if cancelled:
        logger.info('task_cancel_stale_pending_orders 取消 %s 笔', cancelled)
    return cancelled


@shared_task(
    name='bill.tasks.task_settle_due_orders',
    soft_time_limit=300,
    time_limit=360,
)
def task_settle_due_orders():
    """
    每天凌晨自动结算到期的订单：
    扫描所有已完成、未结算、结算时间已到的订单，执行结算（待结算转可提现，扣除佣金）
    """
    from decimal import Decimal, ROUND_HALF_UP
    from django.utils import timezone
    from django.db import transaction
    from django.db.models import Sum
    from bill.models import ProductOrder, ServiceOrder
    from wallet.models import MerchantWallet, MerchantWalletTransaction
    from pay.models import PaymentOrder, PaymentRefund

    now = timezone.now()
    settled_count = 0
    failed_count = 0

    def settle_single_order(order, order_type):
        """结算单个订单"""
        nonlocal settled_count, failed_count
        try:
            # 获取支付单
            payment = (PaymentOrder.objects
                       .filter(order_no=order.order_no, status='paid')
                       .order_by('-created_at')
                       .first())
            if not payment:
                logger.warning('订单 %s 无有效支付单，跳过结算', order.order_no)
                order.is_settled = True  # 标记为已结算，避免重复扫描
                order.save(update_fields=['is_settled', 'updated_at'])
                return

            mw = MerchantWallet.objects.filter(merchant_id=order.merchant_id).first()
            if not mw:
                logger.warning('订单 %s 商家钱包不存在，跳过结算', order.order_no)
                return

            # 计算退款金额
            refunded = (PaymentRefund.objects
                        .filter(payment_order=payment, status='success')
                        .aggregate(s=Sum('refund_amount'))['s']) or Decimal('0')
            settle_amount = payment.amount - refunded
            if settle_amount <= 0:
                # 全额退款，无需结算
                order.is_settled = True
                order.settled_at = now
                order.save(update_fields=['is_settled', 'settled_at', 'updated_at'])
                return

            # 获取佣金率
            merchant = mw.merchant
            rate = Decimal(str(getattr(merchant, 'commission_rate', 0) or 0))
            if rate <= 0 and getattr(merchant, 'category_id', None):
                rate = Decimal(str(getattr(merchant.category, 'commission_rate', 0) or 0))

            commission_amount = (
                    settle_amount * rate / Decimal('100')
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            if commission_amount > settle_amount:
                commission_amount = settle_amount

            with transaction.atomic():
                # 锁定订单，防止重复结算
                if order_type == 'product':
                    order = ProductOrder.objects.select_for_update().get(pk=order.pk)
                else:
                    order = ServiceOrder.objects.select_for_update().get(pk=order.pk)
                if order.is_settled:
                    return  # 已经被其他任务结算过了

                # 待结算转可提现
                mw.settle_pending(
                    amount=settle_amount,
                    related_order_no=order.order_no,
                    related_type=f'{order_type}_order',
                    related_id=order.id,
                    remark=f'订单 {order.order_no} 到期自动结算，佣金率 {rate}%',
                    idempotent_key=f'order_settle_{order.order_no}',
                )

                # 扣除平台佣金
                if commission_amount > 0:
                    mw.change_balance(
                        amount=-commission_amount,
                        action=MerchantWalletTransaction.Action.COMMISSION_DEDUCT,
                        related_order_no=order.order_no,
                        related_type=f'{order_type}_order',
                        related_id=order.id,
                        remark=f'订单 {order.order_no} 平台佣金 {rate}%，扣除 ¥{commission_amount}',
                        idempotent_key=f'order_commission_{order.order_no}',
                    )

                # 标记订单已结算
                order.is_settled = True
                order.settled_at = now
                order.save(update_fields=['is_settled', 'settled_at', 'updated_at'])
                settled_count += 1

        except Exception as e:
            failed_count += 1
            logger.exception('自动结算订单失败 order_no=%s error=%s', order.order_no, str(e))

    # 结算商品订单
    due_product_orders = ProductOrder.objects.filter(
        status=ProductOrder.Status.COMPLETED,
        is_settled=False,
        settle_due_at__lte=now,
    ).order_by('settle_due_at')[:500]  # 每次最多处理500单，避免超时

    for order in due_product_orders:
        settle_single_order(order, 'product')

    # 结算服务订单
    due_service_orders = ServiceOrder.objects.filter(
        status=ServiceOrder.Status.COMPLETED,
        is_settled=False,
        settle_due_at__lte=now,
    ).order_by('settle_due_at')[:500]

    for order in due_service_orders:
        settle_single_order(order, 'service')

    logger.info('自动结算任务完成：成功 %s 单，失败 %s 单', settled_count, failed_count)
    return {'success': settled_count, 'failed': failed_count}