# -*- coding: utf-8 -*-
# orders/views.py

import logging
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone as dj_tz
from django.db.models import Sum, F, Count
from django.utils import timezone
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.views import APIView
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction

from wallet.models import MerchantWalletTransaction, UserWallet, WalletTransaction
from .models import (
    ProductOrder, ServiceOrder, OrderLog,
)
from .serializers import (
    # 用户端
    UserProductOrderListSerializer, UserProductOrderDetailSerializer,
    UserProductOrderCreateSerializer,
    UserServiceOrderListSerializer, UserServiceOrderDetailSerializer,
    UserServiceOrderCreateSerializer,
    OrderCancelSerializer, RefundApplySerializer,
    # 商家端
    MerchantProductOrderListSerializer, MerchantProductOrderDetailSerializer,
    ShipSerializer,
    MerchantServiceOrderListSerializer, MerchantServiceOrderDetailSerializer,
    AssignStaffSerializer, RefundHandleSerializer,
    # 管理端
    AdminProductOrderListSerializer, AdminProductOrderDetailSerializer,
    AdminProductOrderUpdateSerializer,
    AdminServiceOrderListSerializer, AdminServiceOrderDetailSerializer,
    AdminServiceOrderUpdateSerializer,
    AdminForceStatusSerializer, AdminAdjustAmountSerializer,
    # 日志
    OrderLogSerializer, return_coupon,

    create_order_log, StaffServiceOrderDetailSerializer, StaffServiceOrderListSerializer,
)
from .filters import (
    UserProductOrderFilter, UserServiceOrderFilter,
    MerchantProductOrderFilter, MerchantServiceOrderFilter,
    AdminProductOrderFilter, AdminServiceOrderFilter,
    OrderLogFilter,
)
from .paginations import OrderPagination, AdminOrderPagination
from utils.authentication import (
    UserAuthentication, MerchantOrSubAuthentication, ManagerAuthentication,
)
from utils.permission import IsUser, IsMerchant, IsManager
from pay.models import PaymentOrder
from utils.wechat_client import upload_wechat_shipping_info


logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════

def _get_merchant_id(request):
    """从商家认证中取 merchant_id"""
    user = request.user
    if hasattr(user, 'merchant_id'):
        return user.merchant_id  # 子账号 / 员工
    return user.id               # 商家主账号


def _get_order_item_desc(order):
    """
    拼接订单商品/服务描述，用于微信支付和微信订单中心同步。

    兼容不同订单 item 字段：
      - 商品订单：product_name
      - 服务订单：service_name / name / title
    微信发货接口 item_desc 限 120 字。
    """
    items_desc = []
    for item in order.items.all():
        name = (
            getattr(item, 'product_name', None)
            or getattr(item, 'service_name', None)
            or getattr(item, 'name', None)
            or getattr(item, 'title', None)
            or '商品/服务'
        )
        qty = getattr(item, 'quantity', 1) or 1
        items_desc.append(f"{name}x{qty}")

    desc = "，".join(items_desc) or f"订单 {getattr(order, 'order_no', '')}"
    if len(desc) > 120:
        desc = desc[:117] + "..."
    return desc


def _bump_sales(order, order_type, delta):
    """
    更新商品/服务销量(原子自增,异常吃掉,不影响主流程)。

    delta=+1 增加(订单完成时);delta=-1 减少(全额退款时)。
    减法时加 sales_count >= |change| 过滤,防止 PositiveBigIntegerField underflow
    导致 MySQL 1690 错误污染外层事务。
    """
    try:
        if order_type == 'product':
            from product.models import Goods
            for item in order.items.all():
                gid = getattr(item, 'product_id', None)
                qty = getattr(item, 'quantity', 1) or 1
                if not gid:
                    continue
                change = delta * qty
                if change >= 0:
                    Goods.objects.filter(id=gid).update(
                        sales_count=F('sales_count') + change
                    )
                else:
                    Goods.objects.filter(
                        id=gid, sales_count__gte=-change,
                    ).update(
                        sales_count=F('sales_count') + change
                    )
        elif order_type == 'service':
            from services.models import Service
            for item in order.items.all():
                sid = getattr(item, 'service_id', None)
                qty = getattr(item, 'quantity', 1) or 1
                if not sid:
                    continue
                change = delta * qty
                if change >= 0:
                    Service.objects.filter(id=sid).update(
                        total_sales=F('total_sales') + change
                    )
                else:
                    Service.objects.filter(
                        id=sid, total_sales__gte=-change,
                    ).update(
                        total_sales=F('total_sales') + change
                    )
    except Exception:
        logger.exception(
            '更新销量失败 order_no=%s delta=%s',
            getattr(order, 'order_no', '?'), delta,
        )
def _on_order_completed(order, order_type):
    """
    订单完成钩子:
      0) 销量 +1
      1) 计算结算到期时间（根据商家结算周期，不立刻结算）
      2) 发用户积分 points_earned

    注:gold_earned 字段保留作为埋点,当前不发放。
        商品/服务的金币只用于抵扣(coins_deducted),不作为奖励发放。
        异常吃掉,避免阻断订单完成动作。
    """
    # 0) 销量 +1(独立 try,失败不影响后续)
    _bump_sales(order, order_type, +1)

    # 1) 计算结算到期时间，不立刻结算
    if order.merchant_id:
        try:
            from wallet.models import MerchantSettlementConfig
            config = MerchantSettlementConfig.objects.filter(merchant_id=order.merchant_id).first()
            # 默认T+1
            delay_days = 1
            if config:
                cycle = config.settlement_cycle
                if cycle == 'T+7':
                    delay_days = 7
                elif cycle == 'T+15':
                    delay_days = 15
                elif cycle == 'T+30':
                    delay_days = 30
                else: # T+1
                    delay_days = 1
            # 计算结算到期时间
            order.settle_due_at = order.completed_at + timedelta(days=delay_days)
            order.is_settled = False
            order.save(update_fields=['settle_due_at', 'is_settled', 'updated_at'])
        except Exception:
            logger.exception('计算结算到期时间失败 order_no=%s', order.order_no)

    # 2) 发积分(金币奖励未启用,gold_earned 仅做快照埋点)
    points = getattr(order, 'points_earned', 0) or 0
    if points <= 0:
        return

    try:
        user_wallet, _ = UserWallet.objects.get_or_create(user_id=order.user_id)
        user_wallet.change_points(
            amount=points,
            action=WalletTransaction.Action.ORDER_REWARD,
            operator_role='system',
            related_type=f'{order_type}_order',
            related_id=order.id,
            remark=f'订单 {order.order_no} 完成奖励',
            idempotent_key=f'order_points_reward_{order.order_no}',
        )
    except Exception:
        logger.exception('发放积分失败 order_no=%s', order.order_no)

    try:
        from pay.views import _unfreeze_merchant_earns_on_complete
        _unfreeze_merchant_earns_on_complete(order)
    except Exception:
        logger.exception('解冻商家活动金币失败 order_no=%s', order.order_no)


def _on_order_refunded(order, order_type):
    """
    订单全额退款钩子:销量 -1。
    其他钱包逻辑(扣商家、返还金币、撤销积分)由 pay 模块的
    _on_refund_success 负责,这里只管销量。
    """
    if not getattr(order, 'completed_at', None):
        return
    _bump_sales(order, order_type, -1)


def _release_time_slot(service_order):
    """
    释放服务订单关联的预约时段名额。
    在订单取消、退款通过、强制退款时调用。
    幂等:即使 time_slot 不存在也不会抛错。
    """
    if not service_order.time_slot_id:
        return
    try:
        from services.models import ServiceTimeSlot
        from django.db import transaction

        with transaction.atomic():
            slot = ServiceTimeSlot.objects.select_for_update().get(
                id=service_order.time_slot_id,
            )
            if slot.booked_count > 0:
                slot.cancel_book()
    except Exception:
        # 释放失败不影响主流程,只记 log
        logger.exception('释放预约时段失败 order_no=%s', service_order.order_no)


# ══════════════════════════════════════════════════════════════
# ★ 退款审批委托 —— 共用工具
# ══════════════════════════════════════════════════════════════

def _delegate_refund_approve(order, order_type, request, refund_reason_detail=''):
    """
    把"商家同意退款"委托给 pay 模块,真正调微信发起退款。

    返回:(refund_obj, error_msg)
      - refund_obj: 创建的 PaymentRefund 实例(可能为 None,如校验失败)
      - error_msg:  失败时的错误信息(成功时为 None)

    注意:
      - 不在这里改 order.status,等微信回调到了由 pay 模块统一推进。
      - 不在这里调 _on_order_refunded(销量-1),回调里会处理。
    """
    from pay.serializers import ApproveRefundSerializer
    from pay.views import _do_approve_refund
    from rest_framework.exceptions import ValidationError as DRFValidationError

    approve_ser = ApproveRefundSerializer(
        data={
            'order_no':      order.order_no,
            'order_type':    order_type,
            'reason':        'merchant_cancel',
            'reason_detail': refund_reason_detail,
            # 不传 refund_amount → 全额退
        },
        context={
            'request': request,
            'merchant_id_filter': _get_merchant_id(request),
        },
        operator_type='merchant',
    )
    try:
        approve_ser.is_valid(raise_exception=True)
    except DRFValidationError as e:
        # 把 DRF 的校验错误转成简单字符串返回
        return None, f'退款校验失败: {e.detail}'

    refund, err = _do_approve_refund(
        approve_ser,
        operator_type='merchant',
        operator_id=request.user.id,
    )
    return refund, err


# ══════════════════════════════════════════════════════════════
# 微信订单中心同步工具
# ══════════════════════════════════════════════════════════════

WECHAT_PAYMENT_CHANNELS = {
    'wechat_mini', 'wechat_app', 'wechat_h5',
    'wechat', 'wxpay', 'wx_pay', 'miniapp', 'jsapi',
}


def _mask_openid(openid):
    """日志中脱敏 openid，避免完整敏感标识落盘。"""
    if not openid:
        return None
    openid = str(openid)
    if len(openid) <= 10:
        return openid[:3] + '***'
    return openid[:6] + '***' + openid[-4:]


def _sync_wechat_order_center(
    order,
    *,
    logistics_type,
    scene,
    tracking_no=None,
    express_company_name=None,
):
    """
    同步微信小程序订单中心发货/自提信息。

    logistics_type:
      1 = 实体物流
      4 = 用户自提

    设计原则：
      - 同步失败不影响本地发货/核销成功；
      - 但必须打完整日志，方便排查 payment / openid / 微信接口返回；
      - 不再把 channel__in 写死在查询条件里，避免数据库 channel 取值不一致导致直接查不到支付单。
    """
    sync_name = '微信自提信息' if logistics_type == 4 else '微信发货信息'

    try:
        payment = (
            PaymentOrder.objects
            .filter(order_no=order.order_no, status='paid')
            .order_by('-paid_at')
            .first()
        )

        logger.info(
            "准备同步%s scene=%s order_no=%s payment_found=%s payment_channel=%s out_trade_no=%s channel_trade_no=%s",
            sync_name,
            scene,
            order.order_no,
            bool(payment),
            getattr(payment, 'channel', None) if payment else None,
            getattr(payment, 'out_trade_no', None) if payment else None,
            getattr(payment, 'channel_trade_no', None) if payment else None,
        )

        if not payment:
            logger.warning(
                "跳过同步%s：未找到已支付 PaymentOrder scene=%s order_no=%s",
                sync_name,
                scene,
                order.order_no,
            )
            return False

        # 0 元订单不是微信支付单，不需要上传微信订单中心。
        if str(payment.channel_trade_no or '').startswith('ZERO_'):
            logger.info(
                "跳过同步%s：0元订单 scene=%s order_no=%s out_trade_no=%s",
                sync_name,
                scene,
                order.order_no,
                payment.out_trade_no,
            )
            return False

        channel = (getattr(payment, 'channel', '') or '').strip()
        if channel and channel not in WECHAT_PAYMENT_CHANNELS:
            # 不直接 return。很多项目早期 channel 命名不统一，先继续尝试，微信侧会返回明确错误。
            logger.warning(
                "支付渠道不在常见微信渠道列表，仍尝试同步%s scene=%s order_no=%s channel=%s out_trade_no=%s",
                sync_name,
                scene,
                order.order_no,
                channel,
                payment.out_trade_no,
            )

        if not payment.out_trade_no:
            logger.warning(
                "跳过同步%s：PaymentOrder 缺少 out_trade_no scene=%s order_no=%s payment_id=%s",
                sync_name,
                scene,
                order.order_no,
                getattr(payment, 'id', None),
            )
            return False

        wx_auth = order.user.auth_providers.filter(provider='wx_mini').first()
        logger.info(
            "微信授权信息 scene=%s order_no=%s wx_auth_found=%s openid=%s",
            scene,
            order.order_no,
            bool(wx_auth),
            _mask_openid(wx_auth.provider_uid if wx_auth else None),
        )

        if not wx_auth or not wx_auth.provider_uid:
            logger.warning(
                "跳过同步%s：用户没有 wx_mini openid scene=%s order_no=%s user_id=%s",
                sync_name,
                scene,
                order.order_no,
                order.user_id,
            )
            return False

        item_desc = _get_order_item_desc(order)
        ok = upload_wechat_shipping_info(
            out_trade_no=payment.out_trade_no,
            openid=wx_auth.provider_uid,
            logistics_type=logistics_type,
            item_desc=item_desc,
            tracking_no=tracking_no,
            express_company_name=express_company_name,
        )

        logger.info(
            "同步%s完成 scene=%s order_no=%s out_trade_no=%s logistics_type=%s ok=%s",
            sync_name,
            scene,
            order.order_no,
            payment.out_trade_no,
            logistics_type,
            ok,
        )
        return ok

    except Exception as e:
        logger.warning(
            "同步%s异常 scene=%s order_no=%s error=%s",
            sync_name,
            scene,
            getattr(order, 'order_no', None),
            str(e),
            exc_info=True,
        )
        return False


# ══════════════════════════════════════════════════════════════
# 用户端 — 商品订单
# ══════════════════════════════════════════════════════════════

class UserProductOrderViewSet(viewsets.ModelViewSet):
    """
    用户商品订单

    GET    list / retrieve
    POST   create
    POST   {id}/cancel/
    POST   {id}/confirm-receipt/
    POST   {id}/refund-apply/
    """
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]
    pagination_class       = OrderPagination
    filter_backends        = [DjangoFilterBackend]
    filterset_class        = UserProductOrderFilter
    http_method_names      = ['get', 'post']  # 禁 PUT/DELETE

    def get_queryset(self):
        return (
            ProductOrder.objects
            .filter(user=self.request.user, user_deleted=False)
            .prefetch_related('items')
            .order_by('-created_at')
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return UserProductOrderListSerializer
        if self.action == 'create':
            return UserProductOrderCreateSerializer
        return UserProductOrderDetailSerializer

    # ── 取消订单 ──
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        allowed = (
            ProductOrder.Status.PENDING_PAYMENT,
            ProductOrder.Status.PAID,
            ProductOrder.Status.PENDING_PICKUP,  # ← 新增
        )
        if order.status not in allowed:
            return Response({'error': '当前状态无法取消'}, status=status.HTTP_400_BAD_REQUEST)

        ser = OrderCancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        order.status = ProductOrder.Status.CANCELLED
        order.cancel_reason = ser.validated_data.get('cancel_reason', '')
        order.save(update_fields=['status', 'cancel_reason', 'updated_at'])
        return_coupon(order)

        create_order_log(
            order.order_no, 'product', 'cancel',
            request=request, operator_type='user',
            description=order.cancel_reason or '用户取消',
        )
        return Response({'message': '订单已取消'})

    # ── 确认收货(直接到 COMPLETED,触发结算 + 发积分 + 销量+1)──
    @action(detail=True, methods=['post'], url_path='confirm-receipt')
    def confirm_receipt(self, request, pk=None):
        order = self.get_object()
        if order.status != ProductOrder.Status.SHIPPED:
            return Response({'error': '当前状态无法确认收货'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        order.status = ProductOrder.Status.COMPLETED
        order.completed_at = now
        order.save(update_fields=['status', 'completed_at', 'updated_at'])

        create_order_log(
            order.order_no, 'product', 'receive',
            request=request, operator_type='user',
            description='用户确认收货',
        )

        # 触发:销量 +1 + 商家结算 + 发积分
        _on_order_completed(order, 'product')

        return Response({'message': '已确认收货'})

    # ── 申请退款 ──
    @action(detail=True, methods=['post'], url_path='refund-apply')
    def refund_apply(self, request, pk=None):
        order = self.get_object()
        if order.status in (
            ProductOrder.Status.PENDING_PAYMENT,
            ProductOrder.Status.CANCELLED,
            ProductOrder.Status.REFUNDING,
            ProductOrder.Status.REFUNDED,
        ):
            return Response({'error': '当前状态无法申请退款'}, status=status.HTTP_400_BAD_REQUEST)

        ser = RefundApplySerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        order.status = ProductOrder.Status.REFUNDING
        order.save(update_fields=['status', 'updated_at'])

        create_order_log(
            order.order_no, 'product', 'refund_apply',
            request=request, operator_type='user',
            description=ser.validated_data['reason'],
        )
        return Response({'message': '退款申请已提交'})

    # ── 删除订单(软删除,仅终态可删)──
    @action(detail=True, methods=['post'], url_path='delete')
    def soft_delete(self, request, pk=None):
        order = self.get_object()
        if not order.can_user_delete:
            return Response(
                {'error': '只有已完成、已取消或已退款的订单可以删除'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.user_deleted = True
        order.user_deleted_at = timezone.now()
        order.save(update_fields=['user_deleted', 'user_deleted_at', 'updated_at'])
        return Response({'message': '订单已删除'})


# ══════════════════════════════════════════════════════════════
# 用户端 — 服务订单
# ══════════════════════════════════════════════════════════════

def _within_free_cancel_window(order) -> bool:
    """
    判断当前是否还在免费取消窗口内。

    口径(按服务类型分流):
      - appointment / scheduled:基于"距服务开始时间还有多久"判断,
        因为这类有明确的开始时刻。距开始时间 >= free_cancel_hours 才算窗口内。
      - walk_in / on_demand:基于"从支付时间起算的经过时长"判断,
        没有明确开始时刻,用付款时间兜底。

    若商家把 free_cancel_hours_snapshot 设为 0,视为"不允许免费取消",
    始终返回 False(只要超过 0 秒就要扣定金)。
    若 free_cancel_hours_snapshot 未设置(None / 字段缺失),保守视为不允许免费取消。
    """
    free_hours = order.free_cancel_hours_snapshot or 0
    if free_hours <= 0:
        return False

    now = dj_tz.now()

    # ── 预约制:用预约时间判 ──
    if order.service_type == 'appointment' and order.appointment_date:
        from datetime import datetime, time as _time
        start_time = order.appointment_start or _time(0, 0)
        appt_dt = datetime.combine(order.appointment_date, start_time)
        appt_dt = dj_tz.make_aware(appt_dt, dj_tz.get_current_timezone()) \
            if dj_tz.is_naive(appt_dt) else appt_dt
        hours_until_appt = (appt_dt - now).total_seconds() / 3600
        return hours_until_appt >= free_hours

    # ── 周期制:用订阅起始日判 ──
    if order.service_type == 'scheduled' and order.subscription_start_date:
        from datetime import datetime, time as _time
        start_dt = datetime.combine(order.subscription_start_date, _time(0, 0))
        start_dt = dj_tz.make_aware(start_dt, dj_tz.get_current_timezone()) \
            if dj_tz.is_naive(start_dt) else start_dt
        hours_until_start = (start_dt - now).total_seconds() / 3600
        return hours_until_start >= free_hours

    # ── 到店制 / 按需制:从付款时间起算 ──
    if not order.paid_at:
        return True  # 没付款的特殊情况,留给上游判断
    elapsed_hours = (now - order.paid_at).total_seconds() / 3600
    return elapsed_hours <= free_hours

class UserServiceOrderViewSet(viewsets.ModelViewSet):
    """
    用户服务订单

    GET    list / retrieve
    POST   create
    POST   {id}/cancel/
    POST   {id}/refund-apply/
    """
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]
    pagination_class       = OrderPagination
    filter_backends        = [DjangoFilterBackend]
    filterset_class        = UserServiceOrderFilter
    http_method_names      = ['get', 'post']

    def get_queryset(self):
        return (
            ServiceOrder.objects
            .filter(user=self.request.user, user_deleted=False)
            .prefetch_related('items')
            .select_related('assigned_staff')
            .order_by('-created_at')
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return UserServiceOrderListSerializer
        if self.action == 'create':
            return UserServiceOrderCreateSerializer
        return UserServiceOrderDetailSerializer

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        用户取消服务订单。

        业务规则(一次付清 + 违约扣定金):
          - 未支付:直接取消,无退款
          - 已支付 + 免费取消窗口内 + (无定金 或 是用户违约前的早期阶段):
                全额退,走 REFUNDING 流程
          - 已支付 + 超出免费时限 + 有定金:
                扣定金,只退 pay_amount - deposit
          - 已支付 + 超出免费时限 + 无定金:
                走 REFUNDING(等同申请退款,由商家审批)
        """
        order = self.get_object()

        cancellable = (
            ServiceOrder.Status.PENDING_PAYMENT,
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_ACCEPT,
            ServiceOrder.Status.PENDING_ASSIGNMENT,
            ServiceOrder.Status.ASSIGNED,
        )
        if order.status not in cancellable:
            return Response(
                {'error': '当前状态无法取消'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = OrderCancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user_reason = ser.validated_data.get('cancel_reason', '')

        # ════════════════ 1) 未支付:直接取消 ════════════════
        if order.status == ServiceOrder.Status.PENDING_PAYMENT:
            from django.db import transaction
            with transaction.atomic():
                order.status = ServiceOrder.Status.CANCELLED
                order.cancel_reason = user_reason
                order.save(update_fields=['status', 'cancel_reason', 'updated_at'])
                _release_time_slot(order)
                return_coupon(order)

            create_order_log(
                order.order_no, 'service', 'cancel',
                request=request, operator_type='user',
                description=user_reason or '用户取消(未支付)',
            )
            return Response({
                'message': '订单已取消',
                'refund_type': 'none',
            })

        # ════════════════ 2) 已支付:判定免费取消窗口 ════════════════
        deposit = Decimal(order.deposit_amount or 0)
        pay_amount = Decimal(order.pay_amount or 0)
        in_free_window = _within_free_cancel_window(order)

        # ── 2a) 全额退场景:免费窗口内 / 无定金 ──
        if in_free_window or deposit <= 0:
            order.status = ServiceOrder.Status.REFUNDING
            order.save(update_fields=['status', 'updated_at'])
            create_order_log(
                order.order_no, 'service', 'refund_apply',
                request=request, operator_type='user',
                description=(
                    f'免费取消窗口内取消: {user_reason}'
                    if in_free_window
                    else f'用户取消(无定金): {user_reason}'
                ),
            )
            return Response({
                'message': '已申请取消,全额退款审批中',
                'refund_type': 'full',
                'refund_amount': str(pay_amount),
            })

        # ── 2b) 违约扣定金:超出免费时限 + 有定金 ──
        refund_amount = max(Decimal('0'), pay_amount - deposit)

        # 极端情况:实付 <= 定金,退款金额为 0
        if refund_amount <= 0:
            from django.db import transaction
            with transaction.atomic():
                order.status = ServiceOrder.Status.CANCELLED
                order.cancel_reason = (
                    f'{user_reason} | 超出免费时限,定金 ¥{deposit} 不退'
                    if user_reason else
                    f'超出免费时限,定金 ¥{deposit} 不退'
                )
                order.save(update_fields=['status', 'cancel_reason', 'updated_at'])
                _release_time_slot(order)
                # 注意:违约取消不退券、不返还金币,语义上视为"消费已发生"

            create_order_log(
                order.order_no, 'service', 'cancel',
                request=request, operator_type='user',
                description='超出免费取消时限,定金不予退还',
            )
            return Response({
                'message': '订单已取消,定金不予退还',
                'refund_type': 'none',
                'refund_amount': '0.00',
                'deposit_kept': str(deposit),
            })

        # ── 2c) 正常部分退:发起 refund_amount 的退款,扣下 deposit ──
        # 先把订单置为 REFUNDING,然后委托 pay 模块发起部分退款
        order.status = ServiceOrder.Status.REFUNDING
        order.save(update_fields=['status', 'updated_at'])

        from pay.serializers import ApproveRefundSerializer
        from pay.views import _do_approve_refund
        from rest_framework.exceptions import ValidationError as DRFValidationError

        approve_ser = ApproveRefundSerializer(
            data={
                'order_no': order.order_no,
                'order_type': 'service',
                'reason': 'user_cancel',
                'reason_detail': (
                    f'超出免费取消时限,扣定金 ¥{deposit} | {user_reason}'
                    if user_reason else
                    f'超出免费取消时限,扣定金 ¥{deposit}'
                ),
                'refund_amount': str(refund_amount),
            },
            context={
                'request': request,
                'merchant_id_filter': None,  # 用户自己取消,不限商家
            },
            operator_type='user',
        )

        def _rollback_to_paid():
            order.status = ServiceOrder.Status.PAID
            order.save(update_fields=['status', 'updated_at'])

        try:
            approve_ser.is_valid(raise_exception=True)
        except DRFValidationError as e:
            _rollback_to_paid()
            return Response(
                {'error': f'退款校验失败: {e.detail}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refund, err = _do_approve_refund(
            approve_ser,
            operator_type='user',
            operator_id=request.user.id,
        )
        if err:
            _rollback_to_paid()
            return Response(
                {
                    'error': err,
                    'refund_no': refund.refund_no if refund else None,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        create_order_log(
            order.order_no, 'service', 'cancel',
            request=request, operator_type='user',
            description=(
                f'超出免费时限取消,扣定金 ¥{deposit},'
                f'退款 ¥{refund_amount} (退款单 {refund.refund_no}) | {user_reason}'
            ),
        )

        return Response({
            'message': f'已发起退款 ¥{refund_amount},定金 ¥{deposit} 不予退还',
            'refund_type': 'partial',
            'refund_no': refund.refund_no,
            'refund_amount': str(refund_amount),
            'deposit_kept': str(deposit),
        })
    @action(detail=True, methods=['post'], url_path='refund-apply')
    def refund_apply(self, request, pk=None):
        order = self.get_object()
        if order.status in (
            ServiceOrder.Status.PENDING_PAYMENT,
            ServiceOrder.Status.CANCELLED,
            ServiceOrder.Status.REFUNDING,
            ServiceOrder.Status.REFUNDED,
        ):
            return Response({'error': '当前状态无法申请退款'}, status=status.HTTP_400_BAD_REQUEST)

        ser = RefundApplySerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        order.status = ServiceOrder.Status.REFUNDING
        order.save(update_fields=['status', 'updated_at'])

        create_order_log(
            order.order_no, 'service', 'refund_apply',
            request=request, operator_type='user',
            description=ser.validated_data['reason'],
        )
        return Response({'message': '退款申请已提交'})

    # ── 删除订单(软删除,仅终态可删)──
    @action(detail=True, methods=['post'], url_path='delete')
    def soft_delete(self, request, pk=None):
        order = self.get_object()
        if not order.can_user_delete:
            return Response(
                {'error': '只有已完成、已取消或已退款的订单可以删除'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.user_deleted = True
        order.user_deleted_at = timezone.now()
        order.save(update_fields=['user_deleted', 'user_deleted_at', 'updated_at'])
        return Response({'message': '订单已删除'})

# ══════════════════════════════════════════════════════════════
# 商家端 — 商品订单
# ══════════════════════════════════════════════════════════════

class MerchantProductOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    商家商品订单(只读 + 操作)

    GET    list / retrieve
    POST   {id}/accept/
    POST   {id}/ship/
    POST   {id}/refund-handle/
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes     = [IsMerchant]
    pagination_class       = OrderPagination
    filter_backends        = [DjangoFilterBackend]
    filterset_class        = MerchantProductOrderFilter

    def get_queryset(self):
        return (
            ProductOrder.objects
            .filter(merchant_id=_get_merchant_id(self.request))
            .select_related('user')
            .prefetch_related('items')
            .order_by('-created_at')
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return MerchantProductOrderListSerializer
        return MerchantProductOrderDetailSerializer

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """接单(已支付 → 待发货)"""
        order = self.get_object()
        if order.status != ProductOrder.Status.PAID:
            return Response({'error': '当前状态无法接单'}, status=status.HTTP_400_BAD_REQUEST)

        order.status = ProductOrder.Status.PENDING_SHIPMENT
        order.save(update_fields=['status', 'updated_at'])

        create_order_log(
            order.order_no, 'product', 'system_auto',
            request=request, operator_type='merchant',
            description='商家接单',
        )
        return Response({'message': '已接单'})

    @action(detail=True, methods=['post'])
    def ship(self, request, pk=None):
        order = self.get_object()

        if order.delivery_type == ProductOrder.DeliveryType.SELF_PICKUP:
            return Response(
                {'error': '自提订单无需发货,请引导用户到店核销'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.status not in (
            ProductOrder.Status.PAID,
            ProductOrder.Status.PENDING_SHIPMENT,
        ):
            return Response({'error': '当前状态无法发货'}, status=status.HTTP_400_BAD_REQUEST)

        ser = ShipSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        order.shipping_company = ser.validated_data['shipping_company']
        order.shipping_no      = ser.validated_data['shipping_no']
        order.shipped_at       = timezone.now()
        order.status           = ProductOrder.Status.SHIPPED
        order.save(update_fields=[
            'shipping_company', 'shipping_no', 'shipped_at', 'status', 'updated_at',
        ])

        # 同步发货信息到微信订单中心（失败不影响主流程，但会完整打日志）
        _sync_wechat_order_center(
            order,
            logistics_type=1,  # 实体物流
            scene='merchant_product_ship',
            tracking_no=order.shipping_no,
            express_company_name=order.shipping_company,
        )

        create_order_log(
            order.order_no, 'product', 'ship',
            request=request, operator_type='merchant',
            description=f'{order.shipping_company} {order.shipping_no}',
        )
        return Response({'message': '发货成功'})

    @action(detail=True, methods=['post'], url_path='refund-handle')
    def refund_handle(self, request, pk=None):
        """
        商家审批退款(商品订单)。

        ★ 修复点:approve 分支不再直接置 REFUNDED,而是委托 pay 模块调微信。
          - PaymentRefund 创建后状态 pending,等待微信回调
          - 订单状态保持 REFUNDING,微信回调到位后由 pay 推进到 REFUNDED
          - 销量回滚由 pay 模块的 _advance_business_order_to_refunded 触发
          - 商家钱包扣回 / 用户金币返还 / 积分撤销由 pay 的 _on_refund_success 处理
        """
        order = self.get_object()
        if order.status != ProductOrder.Status.REFUNDING:
            return Response({'error': '当前无退款申请'}, status=status.HTTP_400_BAD_REQUEST)

        ser = RefundHandleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        approved = ser.validated_data['action'] == 'approve'

        if approved:
            # ── 委托 pay 模块走真实退款 ──
            refund, err = _delegate_refund_approve(
                order, 'product', request,
                refund_reason_detail=ser.validated_data.get('reason', ''),
            )
            if err:
                return Response(
                    {
                        'error': err,
                        'refund_no': refund.refund_no if refund else None,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            create_order_log(
                order.order_no, 'product', 'refund_approve',
                request=request, operator_type='merchant',
                description=f'已发起微信退款 {refund.refund_no} | {ser.validated_data.get("reason", "")}',
            )
            return Response({
                'message': '退款已发起,等待微信处理',
                'refund_no': refund.refund_no,
            })

        # ── 拒绝退款:撤回到 PAID ──
        order.status = ProductOrder.Status.PAID
        order.save(update_fields=['status', 'updated_at'])

        create_order_log(
            order.order_no, 'product', 'refund_reject',
            request=request, operator_type='merchant',
            description=ser.validated_data.get('reason', ''),
        )
        return Response({'message': '退款已驳回'})

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """
        商品自提订单核销 → COMPLETED
        body: { verify_code?: "12345678" }
              不传 verify_code 也行,商家在订单详情页直接点核销

        触发:销量 +1 + 商家结算 + 发积分
        """
        order = self.get_object()

        if order.delivery_type != ProductOrder.DeliveryType.SELF_PICKUP:
            return Response(
                {'error': '只有自提订单可核销'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 允许从 PAID(兼容旧单)/ PENDING_PICKUP 核销
        allowed = (
            ProductOrder.Status.PAID,
            ProductOrder.Status.PENDING_PICKUP,
        )
        if order.status not in allowed:
            return Response(
                {'error': f'当前状态({order.get_status_display()})无法核销'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 校验核销码(可选)
        code = (request.data.get('verify_code') or '').strip()
        if code and code != order.verify_code:
            return Response({'error': '核销码错误'}, status=status.HTTP_400_BAD_REQUEST)

        # 校验有效期
        if order.verify_expire_at and timezone.now() > order.verify_expire_at:
            return Response(
                {'error': '核销码已过期,请联系平台处理'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 核销 → 直接完成(自提没有"等用户确认"这一步)
        now = timezone.now()
        order.status = ProductOrder.Status.COMPLETED
        order.verified_at = now
        order.completed_at = now
        update_fields = ['status', 'verified_at', 'completed_at', 'updated_at']

        # 记录核销员工
        staff = getattr(request.user, 'staff', None)
        if staff:
            order.verified_by_staff = staff
            update_fields.append('verified_by_staff')

        order.save(update_fields=update_fields)

        # 同步自提信息到微信订单中心（失败不影响主流程，但会完整打日志）
        _sync_wechat_order_center(
            order,
            logistics_type=4,  # 用户自提
            scene='merchant_product_verify',
        )

        # 触发订单完成钩子：计算结算到期时间、销量+1、发积分
        _on_order_completed(order, 'product')

        create_order_log(
            order.order_no, 'product', 'verify',
            request=request, operator_type='merchant',
            description=f'自提核销 {code or ""}'.strip(),
        )

        return Response({
            'message': '核销成功',
            'order': MerchantProductOrderDetailSerializer(order).data,
        })

    @action(detail=False, methods=['post'], url_path='verify-by-code')
    def verify_by_code(self, request):
        """
        商家端扫码 / 输码核销(商品自提)
        body: { verify_code: "12345678" }
        """
        code = (request.data.get('verify_code') or '').strip()
        if not code:
            return Response({'error': '请输入核销码'}, status=status.HTTP_400_BAD_REQUEST)

        merchant_id = _get_merchant_id(request)
        active_statuses = [
            ProductOrder.Status.PAID,
            ProductOrder.Status.PENDING_PICKUP,
        ]

        order = ProductOrder.objects.filter(
            merchant_id=merchant_id,
            verify_code=code,
            delivery_type=ProductOrder.DeliveryType.SELF_PICKUP,
            verified_at__isnull=True,
            status__in=active_statuses,
        ).first()

        if not order:
            return Response(
                {'error': '核销码无效或已使用'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if order.verify_expire_at and timezone.now() > order.verify_expire_at:
            return Response(
                {'error': '核销码已过期'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        order.status = ProductOrder.Status.COMPLETED
        order.verified_at = now
        order.completed_at = now
        update_fields = ['status', 'verified_at', 'completed_at', 'updated_at']

        staff = getattr(request.user, 'staff', None)
        if staff:
            order.verified_by_staff = staff
            update_fields.append('verified_by_staff')

        order.save(update_fields=update_fields)

        # 同步自提信息到微信订单中心（失败不影响主流程，但会完整打日志）
        _sync_wechat_order_center(
            order,
            logistics_type=4,  # 用户自提
            scene='merchant_product_verify_by_code',
        )

        create_order_log(
            order.order_no, 'product', 'verify',
            request=request, operator_type='merchant',
            description=f'扫码核销 {code}',
        )

        _on_order_completed(order, 'product')

        return Response({
            'message': '核销成功',
            'order': MerchantProductOrderDetailSerializer(order).data,
        })

    @action(detail=True, methods=['post'], url_path='force-verify')
    def force_verify(self, request, pk=None):
        """
        超时补核销(自提商品)——特殊入口。
        仅用于商家忘了及时核销、核销码已过期的少数情况;
        正常核销请继续走 verify / verify-by-code(过期仍会拦截)。
        与普通核销的唯一区别:即便核销码过期也放行。
        """
        order = self.get_object()

        if order.delivery_type != ProductOrder.DeliveryType.SELF_PICKUP:
            return Response({'error': '只有自提订单可核销'}, status=status.HTTP_400_BAD_REQUEST)

        allowed = (
            ProductOrder.Status.PAID,
            ProductOrder.Status.PENDING_PICKUP,
        )
        if order.status not in allowed:
            return Response(
                {'error': f'当前状态({order.get_status_display()})无法核销'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 可选:传了核销码才核对,不传直接补核销
        code = (request.data.get('verify_code') or '').strip()
        if code and code != order.verify_code:
            return Response({'error': '核销码错误'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        expired = bool(order.verify_expire_at and now > order.verify_expire_at)

        order.status = ProductOrder.Status.COMPLETED
        order.verified_at = now
        order.completed_at = now
        update_fields = ['status', 'verified_at', 'completed_at', 'updated_at']

        staff = getattr(request.user, 'staff', None)
        if staff:
            order.verified_by_staff = staff
            update_fields.append('verified_by_staff')

        order.save(update_fields=update_fields)

        # 同步自提信息到微信订单中心（失败不影响主流程，但会完整打日志）
        _sync_wechat_order_center(
            order,
            logistics_type=4,  # 用户自提
            scene='merchant_product_force_verify',
        )

        # 触发订单完成钩子：计算结算到期时间、销量+1、发积分
        _on_order_completed(order, 'product')

        create_order_log(
            order.order_no, 'product', 'verify',
            request=request, operator_type='merchant',
            description=('超时补核销' if expired else '补核销') + (f' {code}' if code else ''),
        )

        return Response({
            'message': '核销成功',
            'order': MerchantProductOrderDetailSerializer(order).data,
        })


# ══════════════════════════════════════════════════════════════
# 商家端 — 服务订单
# ══════════════════════════════════════════════════════════════

class MerchantServiceOrderViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    商家服务订单(只读 + 操作)

    GET    list / retrieve
    POST   {id}/accept/
    POST   {id}/assign/
    POST   {id}/start-service/
    POST   {id}/complete/
    POST   {id}/verify/
    POST   {id}/refund-handle/
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes     = [IsMerchant]
    pagination_class       = OrderPagination
    filter_backends        = [DjangoFilterBackend]
    filterset_class        = MerchantServiceOrderFilter

    def get_queryset(self):
        return (
            ServiceOrder.objects
            .filter(merchant_id=_get_merchant_id(self.request))
            .select_related('user', 'assigned_staff')
            .prefetch_related('items')
            .order_by('-created_at')
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return MerchantServiceOrderListSerializer
        return MerchantServiceOrderDetailSerializer

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """接单(已支付 → 待派单)"""
        order = self.get_object()
        if order.status != ServiceOrder.Status.PAID:
            return Response({'error': '当前状态无法接单'}, status=status.HTTP_400_BAD_REQUEST)

        order.status = ServiceOrder.Status.PENDING_ASSIGNMENT
        order.save(update_fields=['status', 'updated_at'])

        create_order_log(
            order.order_no, 'service', 'system_auto',
            request=request, operator_type='merchant',
            description='商家接单',
        )
        return Response({'message': '已接单'})

    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        """
        商家派单 / 强制改派(自动判断)

        - 状态 PAID / PENDING_ASSIGNMENT → 视为首次派单(直接 assign_staff)
        - 状态 ASSIGNED                  → 视为强制改派(走 force_transfer)
        - 状态 PENDING_ACCEPT(自动派单中)→ 视为商家强制接管,先取消 PENDING transfer

        body: { staff_id, reason?, force_urgent?: bool }
        """
        from staffs.models import Staff
        from bill.models import OrderTransfer
        from bill.models import _create_staff_time_slot

        order = self.get_object()

        # 状态校验:允许商家在以下任一状态下派单/改派
        allowed_statuses = (
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_ASSIGNMENT,
            ServiceOrder.Status.PENDING_ACCEPT,
            ServiceOrder.Status.ASSIGNED,
        )
        if order.status not in allowed_statuses:
            return Response(
                {'error': f'当前状态({order.get_status_display()})无法派单'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ser = AssignStaffSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        staff_id = ser.validated_data['staff_id']
        reason = ser.validated_data['reason']
        force_urgent = ser.validated_data['force_urgent']

        # 加载员工 + 商家归属校验
        try:
            staff = Staff.objects.get(
                id=staff_id, merchant_id=_get_merchant_id(request),
            )
        except Staff.DoesNotExist:
            return Response(
                {'error': '员工不存在或不属于本店'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 业务校验
        if staff.status != Staff.Status.ACTIVE:
            return Response(
                {'error': '该员工已暂停接单或离职'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if staff.verification_status == Staff.VerificationStatus.PENDING:
            return Response(
                {'error': '该员工实名认证待审核,暂不可派单'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.is_urgent and not staff.can_handle_urgent and not force_urgent:
            return Response(
                {
                    'error': '订单为紧急服务,该员工未开启「可接紧急」',
                    'need_force_urgent': True,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.assigned_staff_id == staff.id:
            return Response(
                {'error': '该员工已是当前指派员工'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 核心:根据状态分支处理 ──
        is_reassign = (order.status == ServiceOrder.Status.ASSIGNED)
        is_takeover = (order.status == ServiceOrder.Status.PENDING_ACCEPT)

        try:
            if is_reassign:
                # 强制改派(必须递增 transfer_count、撤旧建新时段)
                old_staff = order.assigned_staff
                order.force_transfer(
                    staff,
                    initiated_by=OrderTransfer.InitiatedBy.MERCHANT,
                    reason=reason,
                )
                log_action = 'transfer'
                desc = f'商家强制改派:{old_staff.name if old_staff else "无"} → {staff.name}'
                msg = f'已改派给 {staff.name}'

            elif is_takeover:
                # 商家在自动派单过程中接管 → 取消所有 PENDING,直接派给指定员工
                from django.db import transaction
                with transaction.atomic():
                    locked = ServiceOrder.objects.select_for_update().get(pk=order.pk)
                    # 取消所有 PENDING 转单
                    OrderTransfer.objects.filter(
                        order=locked,
                        status=OrderTransfer.Status.PENDING,
                    ).update(status=OrderTransfer.Status.CANCELLED)
                    # 直接派单
                    locked.assigned_staff = staff
                    locked.assigned_at = timezone.now()
                    locked.status = ServiceOrder.Status.ASSIGNED
                    locked.pending_accept_deadline = None
                    locked.save(update_fields=[
                        'assigned_staff', 'assigned_at', 'status',
                        'pending_accept_deadline', 'updated_at',
                    ])
                    _create_staff_time_slot(locked, staff)
                    order = locked
                log_action = 'assign'
                desc = f'商家接管自动派单流程,直接派单给 {staff.name}'
                msg = f'已派单给 {staff.name}'

            else:
                # 首次派单(PAID / PENDING_ASSIGNMENT)
                from django.db import transaction
                with transaction.atomic():
                    locked = ServiceOrder.objects.select_for_update().get(pk=order.pk)
                    locked.assign_staff(staff)
                    _create_staff_time_slot(locked, staff)
                    order = locked
                log_action = 'assign'
                desc = f'派单给 {staff.name}'
                msg = f'已派单给 {staff.name}'

            if reason:
                desc += f' | {reason}'

        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        create_order_log(
            order.order_no, 'service', log_action,
            request=request, operator_type='merchant',
            description=desc,
        )

        return Response({'message': msg})

    @action(detail=True, methods=['post'], url_path='start-service')
    def start_service(self, request, pk=None):
        order = self.get_object()
        if order.status != ServiceOrder.Status.ASSIGNED:
            return Response({'error': '当前状态无法开始服务'}, status=status.HTTP_400_BAD_REQUEST)

        order.status = ServiceOrder.Status.IN_SERVICE
        order.service_start_at = timezone.now()
        order.save(update_fields=['status', 'service_start_at', 'updated_at'])

        create_order_log(
            order.order_no, 'service', 'service_start',
            request=request, operator_type='merchant',
            description='服务开始',
        )
        return Response({'message': '服务已开始'})

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """商家点完成 → 触发结算 + 发积分 + 销量+1"""
        order = self.get_object()
        if order.status != ServiceOrder.Status.IN_SERVICE:
            return Response({'error': '当前状态无法完成'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        order.status         = ServiceOrder.Status.COMPLETED
        order.service_end_at = now
        order.completed_at   = now
        order.save(update_fields=['status', 'service_end_at', 'completed_at', 'updated_at'])

        # 同步服务完成信息到微信订单中心。服务类线下交付/到店服务按用户自提处理。
        _sync_wechat_order_center(
            order,
            logistics_type=4,  # 用户自提/线下交付
            scene='merchant_service_complete',
        )

        create_order_log(
            order.order_no, 'service', 'complete',
            request=request, operator_type='merchant',
            description='服务完成',
        )

        # 触发:销量 +1 + 商家结算 + 发积分
        _on_order_completed(order, 'service')

        return Response({'message': '服务已完成'})

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        """核销(到店服务,核销即完成 → 触发结算 + 发积分 + 销量+1)"""
        order = self.get_object()
        is_walk_in_paid = (
                order.service_type == 'walk_in'
                and order.status == ServiceOrder.Status.PAID
        )
        if order.status != ServiceOrder.Status.PENDING_USE and not is_walk_in_paid:
            return Response({'error': '当前状态无法核销'}, status=status.HTTP_400_BAD_REQUEST)

        code = request.data.get('verify_code', '')
        if code and code != order.verify_code:
            return Response({'error': '核销码错误'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        order.status       = ServiceOrder.Status.COMPLETED
        order.verified_at  = now
        order.completed_at = now
        order.save(update_fields=['status', 'verified_at', 'completed_at', 'updated_at'])

        # 同步服务核销信息到微信订单中心。到店/核销类服务按用户自提处理。
        _sync_wechat_order_center(
            order,
            logistics_type=4,  # 用户自提/线下交付
            scene='merchant_service_verify',
        )

        create_order_log(
            order.order_no, 'service', 'verify',
            request=request, operator_type='merchant',
            description='核销成功',
        )

        # 触发:销量 +1 + 商家结算 + 发积分
        _on_order_completed(order, 'service')

        return Response({'message': '核销成功'})

    @action(detail=True, methods=['post'], url_path='refund-handle')
    def refund_handle(self, request, pk=None):
        """
        商家审批退款(服务订单)。

        ★ 修复点:approve 分支不再直接置 REFUNDED,而是委托 pay 模块调微信。
          - 服务订单特有:释放预约时段、取消员工时段(这些不依赖微信回调,可立即做)
          - 订单状态保持 REFUNDING,微信回调到位后由 pay 推进到 REFUNDED
          - 销量回滚由 pay 模块的 _advance_business_order_to_refunded 触发
          - 商家钱包扣回 / 用户金币返还 / 积分撤销由 pay 的 _on_refund_success 处理
        """
        order = self.get_object()
        if order.status != ServiceOrder.Status.REFUNDING:
            return Response({'error': '当前无退款申请'}, status=status.HTTP_400_BAD_REQUEST)

        ser = RefundHandleSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        approved = ser.validated_data['action'] == 'approve'

        if approved:
            # ── 委托 pay 模块走真实退款 ──
            refund, err = _delegate_refund_approve(
                order, 'service', request,
                refund_reason_detail=ser.validated_data.get('reason', ''),
            )
            if err:
                return Response(
                    {
                        'error': err,
                        'refund_no': refund.refund_no if refund else None,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ── 服务订单特有:释放预约时段、取消员工时段 ──
            # (这些是排班资源,不依赖微信回调,可立即释放)
            try:
                _release_time_slot(order)
                if order.assigned_staff_id:
                    from bill.models import _cancel_staff_time_slot
                    _cancel_staff_time_slot(order, order.assigned_staff)
            except Exception:
                logger.exception('退款时释放排班资源失败 order_no=%s', order.order_no)

            create_order_log(
                order.order_no, 'service', 'refund_approve',
                request=request, operator_type='merchant',
                description=f'已发起微信退款 {refund.refund_no} | {ser.validated_data.get("reason", "")}',
            )
            return Response({
                'message': '退款已发起,等待微信处理',
                'refund_no': refund.refund_no,
            })

        # ── 拒绝退款:撤回到 PAID ──
        order.status = ServiceOrder.Status.PAID
        order.save(update_fields=['status', 'updated_at'])

        create_order_log(
            order.order_no, 'service', 'refund_reject',
            request=request, operator_type='merchant',
            description=ser.validated_data.get('reason', ''),
        )
        return Response({'message': '退款已驳回'})

    @action(detail=False, methods=['post'], url_path='verify-by-code')
    def verify_by_code(self, request):
        """
        商家端扫码 / 输码核销
        body: { verify_code: "12345678" }

        流程:
          1. 按 merchant_id + verify_code 查活跃订单
          2. 同 merchant 内由 unique constraint 保证只会命中一条
          3. 调 verify_order 推进状态
        """
        code = (request.data.get('verify_code') or '').strip()
        if not code:
            return Response({'error': '请输入核销码'}, status=status.HTTP_400_BAD_REQUEST)

        merchant_id = _get_merchant_id(request)
        active_statuses = [
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_USE,
            ServiceOrder.Status.ASSIGNED,
            ServiceOrder.Status.IN_SERVICE,
        ]

        order = ServiceOrder.objects.filter(
            merchant_id=merchant_id,
            verify_code=code,
            verified_at__isnull=True,
            status__in=active_statuses,
        ).first()

        if not order:
            return Response(
                {'error': '核销码无效或已使用'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 校验有效期
        if order.verify_expire_at and timezone.now() > order.verify_expire_at:
            return Response(
                {'error': '核销码已过期'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # 取当前操作员工(如果是子账号绑定了 staff)
            staff = None
            if hasattr(request.user, 'staff'):
                staff = request.user.staff
            order.verify_order(by_staff=staff)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        create_order_log(
            order.order_no, 'service', 'verify',
            request=request, operator_type='merchant',
            description=f'扫码核销 {code}',
        )

        # 服务扫码核销完成后，同步微信订单中心。
        if order.status == ServiceOrder.Status.COMPLETED:
            _sync_wechat_order_center(
                order,
                logistics_type=4,  # 用户自提/线下交付
                scene='merchant_service_verify_by_code',
            )

        # 触发完成钩子:销量+1 / 商家结算 / 发积分
        if order.status == ServiceOrder.Status.COMPLETED:
            _on_order_completed(order, 'service')

        return Response({
            'message': '核销成功',
            'order': MerchantServiceOrderDetailSerializer(order).data,
        })

    @action(detail=True, methods=['post'], url_path='force-verify')
    def force_verify(self, request, pk=None):
        """
        超时补核销(服务)——特殊入口。
        仅用于核销码已过期、商家忘了及时核销的少数情况;
        正常核销请继续走 verify / verify-by-code(过期仍会拦截)。
        逻辑与本类 verify 一致,唯一区别:即便核销码过期也放行。
        """
        order = self.get_object()

        is_walk_in_paid = (
                order.service_type == 'walk_in'
                and order.status == ServiceOrder.Status.PAID
        )
        if order.status != ServiceOrder.Status.PENDING_USE and not is_walk_in_paid:
            return Response({'error': '当前状态无法核销'}, status=status.HTTP_400_BAD_REQUEST)

        code = (request.data.get('verify_code') or '').strip()
        if code and code != order.verify_code:
            return Response({'error': '核销码错误'}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        expired = bool(order.verify_expire_at and now > order.verify_expire_at)

        order.status = ServiceOrder.Status.COMPLETED
        order.verified_at = now
        order.completed_at = now
        update_fields = ['status', 'verified_at', 'completed_at', 'updated_at']

        staff = getattr(request.user, 'staff', None)
        if staff:
            order.verified_by_staff = staff
            update_fields.append('verified_by_staff')

        order.save(update_fields=update_fields)

        # 服务强制核销/补核销也同步微信订单中心，避免商家走特殊入口时漏同步。
        _sync_wechat_order_center(
            order,
            logistics_type=4,  # 用户自提/线下交付
            scene='merchant_service_force_verify',
        )

        create_order_log(
            order.order_no, 'service', 'verify',
            request=request, operator_type='merchant',
            description=('超时补核销' if expired else '补核销') + (f' {code}' if code else ''),
        )

        _on_order_completed(order, 'service')

        return Response({
            'message': '核销成功',
            'order': MerchantServiceOrderDetailSerializer(order).data,
        })


# ══════════════════════════════════════════════════════════════
# 管理端 — 商品订单
# ══════════════════════════════════════════════════════════════

class AdminProductOrderViewSet(viewsets.ModelViewSet):
    """
    管理端商品订单(完整读写)

    GET    list / retrieve
    PUT    update
    POST   {id}/force-status/
    POST   {id}/adjust-amount/
    POST   {id}/force-refund/
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes     = [IsManager]
    pagination_class       = AdminOrderPagination
    filter_backends        = [DjangoFilterBackend]
    filterset_class        = AdminProductOrderFilter
    http_method_names      = ['get', 'put', 'patch', 'post']

    def get_queryset(self):
        return ProductOrder.objects.select_related('user').prefetch_related('items').order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return AdminProductOrderListSerializer
        if self.action in ('update', 'partial_update'):
            return AdminProductOrderUpdateSerializer
        return AdminProductOrderDetailSerializer

    @action(detail=True, methods=['post'], url_path='force-status')
    def force_status(self, request, pk=None):
        order = self.get_object()
        ser = AdminForceStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        new_status     = ser.validated_data['status']
        valid_statuses = [c[0] for c in ProductOrder.Status.choices]
        if new_status not in valid_statuses:
            return Response(
                {'error': f'无效状态,可选: {valid_statuses}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_status    = order.status
        order.status  = new_status
        update_fields = ['status', 'updated_at']

        if new_status == ProductOrder.Status.COMPLETED and not order.completed_at:
            order.completed_at = timezone.now()
            update_fields.append('completed_at')
        if new_status == ProductOrder.Status.CANCELLED:
            order.cancel_reason = ser.validated_data['reason']
            update_fields.append('cancel_reason')

        order.save(update_fields=update_fields)

        # 取消/退款时释放预约时段(商品订单一般没有,但保持对称无害)
        if new_status in (ProductOrder.Status.CANCELLED, ProductOrder.Status.REFUNDED):
            _release_time_slot(order)
            return_coupon(order)

        create_order_log(
            order.order_no, 'product', 'system_auto',
            request=request, operator_type='admin',
            description=f'管理员强制: {old_status}→{new_status}, 原因: {ser.validated_data["reason"]}',
        )

        # 强制改成 COMPLETED 也触发钱包结算 + 发积分 + 销量+1(幂等不会重复发)
        if new_status == ProductOrder.Status.COMPLETED:
            _on_order_completed(order, 'product')
        # 强制改成 REFUNDED 销量-1(只有从非 REFUNDED 改过来才扣)
        elif new_status == ProductOrder.Status.REFUNDED and old_status != ProductOrder.Status.REFUNDED:
            _on_order_refunded(order, 'product')

        return Response({'message': f'状态已变更为 {new_status}'})

    @action(detail=True, methods=['post'], url_path='adjust-amount')
    def adjust_amount(self, request, pk=None):
        """
        商品订单可调整:pay_amount / discount_amount / freight_amount
        """
        order = self.get_object()
        ser = AdminAdjustAmountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        adjustable = ('pay_amount', 'discount_amount', 'freight_amount')
        changes, save_fields = [], []
        for field in adjustable:
            new_val = ser.validated_data.get(field)
            if new_val is not None:
                old_val = getattr(order, field)
                setattr(order, field, new_val)
                changes.append(f'{field}: {old_val}→{new_val}')
                save_fields.append(field)

        order.save(update_fields=save_fields + ['updated_at'])
        create_order_log(
            order.order_no, 'product', 'modify_price',
            request=request, operator_type='admin',
            description=f'管理员调价: {", ".join(changes)}; 原因: {ser.validated_data["reason"]}',
        )
        return Response({'message': '金额已调整'})

    @action(detail=True, methods=['post'], url_path='force-refund')
    def force_refund(self, request, pk=None):
        order = self.get_object()
        reason     = request.data.get('reason', '管理员强制退款')
        old_status = order.status

        order.status = ProductOrder.Status.REFUNDED
        order.save(update_fields=['status', 'updated_at'])
        return_coupon(order)

        # 销量 -1(只有从非 REFUNDED 改过来才扣,避免重复)
        if old_status != ProductOrder.Status.REFUNDED:
            _on_order_refunded(order, 'product')

        create_order_log(
            order.order_no, 'product', 'refund_approve',
            request=request, operator_type='admin',
            description=f'管理员强制退款({old_status}→refunded): {reason}',
        )
        return Response({'message': '已强制退款'})


# ══════════════════════════════════════════════════════════════
# 管理端 — 服务订单
# ══════════════════════════════════════════════════════════════

class AdminServiceOrderViewSet(viewsets.ModelViewSet):
    """
    管理端服务订单(完整读写)

    GET    list / retrieve
    PUT    update
    POST   {id}/force-status/
    POST   {id}/adjust-amount/
    POST   {id}/force-refund/
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes     = [IsManager]
    pagination_class       = AdminOrderPagination
    filter_backends        = [DjangoFilterBackend]
    filterset_class        = AdminServiceOrderFilter
    http_method_names      = ['get', 'put', 'patch', 'post']

    def get_queryset(self):
        return (
            ServiceOrder.objects
            .select_related('user', 'assigned_staff')
            .prefetch_related('items')
            .order_by('-created_at')
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return AdminServiceOrderListSerializer
        if self.action in ('update', 'partial_update'):
            return AdminServiceOrderUpdateSerializer
        return AdminServiceOrderDetailSerializer

    @action(detail=True, methods=['post'], url_path='force-status')
    def force_status(self, request, pk=None):
        order = self.get_object()
        ser = AdminForceStatusSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        new_status     = ser.validated_data['status']
        valid_statuses = [c[0] for c in ServiceOrder.Status.choices]
        if new_status not in valid_statuses:
            return Response(
                {'error': f'无效状态,可选: {valid_statuses}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_status    = order.status
        order.status  = new_status
        update_fields = ['status', 'updated_at']

        if new_status == ServiceOrder.Status.COMPLETED and not order.completed_at:
            order.completed_at = timezone.now()
            update_fields.append('completed_at')
        if new_status == ServiceOrder.Status.CANCELLED:
            order.cancel_reason = ser.validated_data['reason']
            update_fields.append('cancel_reason')

        order.save(update_fields=update_fields)
        # ★ 取消或退款时统一退券 + 释放时段
        if new_status in (ServiceOrder.Status.CANCELLED, ServiceOrder.Status.REFUNDED):
            _release_time_slot(order)
            return_coupon(order)
        create_order_log(
            order.order_no, 'service', 'system_auto',
            request=request, operator_type='admin',
            description=f'管理员强制: {old_status}→{new_status}, 原因: {ser.validated_data["reason"]}',
        )

        # 强制改成 COMPLETED 也触发钱包结算 + 发积分 + 销量+1
        if new_status == ServiceOrder.Status.COMPLETED:
            _on_order_completed(order, 'service')
        # 强制改成 REFUNDED 销量-1
        elif new_status == ServiceOrder.Status.REFUNDED and old_status != ServiceOrder.Status.REFUNDED:
            _on_order_refunded(order, 'service')

        return Response({'message': f'状态已变更为 {new_status}'})

    @action(detail=True, methods=['post'], url_path='adjust-amount')
    def adjust_amount(self, request, pk=None):
        """
        服务订单没有 freight_amount,只调整:pay_amount / discount_amount
        """
        order = self.get_object()
        ser = AdminAdjustAmountSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        adjustable = ('pay_amount', 'discount_amount')
        changes, save_fields = [], []
        for field in adjustable:
            new_val = ser.validated_data.get(field)
            if new_val is not None:
                old_val = getattr(order, field)
                setattr(order, field, new_val)
                changes.append(f'{field}: {old_val}→{new_val}')
                save_fields.append(field)

        if not save_fields:
            return Response({'error': '没有可调整的金额字段'}, status=status.HTTP_400_BAD_REQUEST)

        order.save(update_fields=save_fields + ['updated_at'])
        create_order_log(
            order.order_no, 'service', 'modify_price',
            request=request, operator_type='admin',
            description=f'管理员调价: {", ".join(changes)}; 原因: {ser.validated_data["reason"]}',
        )
        return Response({'message': '金额已调整'})

    @action(detail=True, methods=['post'], url_path='force-refund')
    def force_refund(self, request, pk=None):
        order = self.get_object()
        reason     = request.data.get('reason', '管理员强制退款')
        old_status = order.status

        order.status = ServiceOrder.Status.REFUNDED
        order.save(update_fields=['status', 'updated_at'])
        _release_time_slot(order)
        return_coupon(order)
        if order.assigned_staff_id:
            from bill.models import _cancel_staff_time_slot
            _cancel_staff_time_slot(order, order.assigned_staff)

        # 销量 -1
        if old_status != ServiceOrder.Status.REFUNDED:
            _on_order_refunded(order, 'service')

        create_order_log(
            order.order_no, 'service', 'refund_approve',
            request=request, operator_type='admin',
            description=f'管理员强制退款({old_status}→refunded): {reason}',
        )
        return Response({'message': '已强制退款'})


# ══════════════════════════════════════════════════════════════
# 管理端 — 订单日志
# ══════════════════════════════════════════════════════════════

class AdminOrderLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    管理端订单日志(只读)

    GET /api/admin/order-logs/?order_no=xxx
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes     = [IsManager]
    serializer_class       = OrderLogSerializer
    pagination_class       = AdminOrderPagination
    filter_backends        = [DjangoFilterBackend]
    filterset_class        = OrderLogFilter

    def get_queryset(self):
        return OrderLog.objects.order_by('-created_at')


# ══════════════════════════════════════════════════════════════
# 员工端 - 服务订单(查看自己接的单 + 开始/完成/核销)
# ══════════════════════════════════════════════════════════════

from utils.authentication import StaffAuthentication
from utils.permission import IsStaff


class StaffServiceOrderViewSet(viewsets.GenericViewSet):
    """
    员工端服务订单

    GET    /api/staff/service-orders/                     我的订单列表
    GET    /api/staff/service-orders/{id}/                订单详情
    POST   /api/staff/service-orders/{id}/start_service/  开始服务
    POST   /api/staff/service-orders/{id}/complete/       完成服务
    POST   /api/staff/service-orders/{id}/verify/         核销
    GET    /api/staff/service-orders/counts/              各状态订单数
    """
    authentication_classes = [StaffAuthentication]
    permission_classes = [IsStaff]
    filter_backends = [DjangoFilterBackend]

    def get_queryset(self):
        return ServiceOrder.objects.filter(
            assigned_staff=self.request.user,
        ).select_related('assigned_staff').prefetch_related(
            'items', 'transfer_records',
        ).order_by('-assigned_at', '-created_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return StaffServiceOrderDetailSerializer
        return StaffServiceOrderListSerializer

    def list(self, request):
        qs = self.get_queryset()

        # ?status=assigned 或 ?status=assigned,in_service
        status_filter = request.query_params.get('status')
        if status_filter:
            statuses = [s.strip() for s in status_filter.split(',') if s.strip()]
            qs = qs.filter(status__in=statuses)

        # ?keyword= 模糊订单号 / 客户姓名 / 电话
        keyword = request.query_params.get('keyword')
        if keyword:
            from django.db.models import Q
            qs = qs.filter(
                Q(order_no__icontains=keyword)
                | Q(receiver_name__icontains=keyword)
                | Q(receiver_phone__icontains=keyword)
            )

        # ?appointment_date=2026-05-08
        date = request.query_params.get('appointment_date')
        if date:
            qs = qs.filter(appointment_date=date)

        # ?is_urgent=true
        if request.query_params.get('is_urgent') in ('true', '1', 'yes'):
            qs = qs.filter(is_urgent=True)

        page = self.paginate_queryset(qs)
        if page is not None:
            ser = self.get_serializer(page, many=True)
            return self.get_paginated_response(ser.data)
        return Response(self.get_serializer(qs, many=True).data)

    def retrieve(self, request, pk=None):
        try:
            order = self.get_queryset().get(pk=pk)
        except ServiceOrder.DoesNotExist:
            return Response(
                {'error': '订单不存在或不属于你'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=['post'], url_path='start_service')
    def start_service(self, request, pk=None):
        try:
            order = self.get_queryset().get(pk=pk)
        except ServiceOrder.DoesNotExist:
            return Response(
                {'error': '订单不存在或不属于你'},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            order.start_service()
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        create_order_log(
            order.order_no, 'service', 'service_start',
            request=request, operator_type='staff',
            description=f'员工 {request.user.name} 开始服务',
        )
        return Response({
            'message': '已开始服务',
            'status': order.status,
            'service_start_at': order.service_start_at,
        })

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        try:
            order = self.get_queryset().get(pk=pk)
        except ServiceOrder.DoesNotExist:
            return Response(
                {'error': '订单不存在或不属于你'},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            order.complete_service()
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        create_order_log(
            order.order_no, 'service', 'complete',
            request=request, operator_type='staff',
            description=f'员工 {request.user.name} 完成服务',
        )

        # complete_service 内部统一推到 COMPLETED,直接触发完成钩子
        _on_order_completed(order, 'service')

        return Response({
            'message': '服务已完成',
            'status': order.status,
            'completed_at': order.completed_at,
        })

    @action(detail=False, methods=['get'])
    def counts(self, request):
        """各状态订单数 — 员工端底部 tab 徽章用"""
        from django.db.models import Count
        rows = self.get_queryset().values('status').annotate(c=Count('id'))
        result = {row['status']: row['c'] for row in rows}
        # 进行中 = assigned + in_service
        in_progress = result.get('assigned', 0) + result.get('in_service', 0)
        return Response({
            'assigned': result.get('assigned', 0),
            'in_service': result.get('in_service', 0),
            'in_progress': in_progress,
            'completed': result.get('completed', 0),
            'cancelled': result.get('cancelled', 0),
            'refunding': result.get('refunding', 0),
            'total': sum(result.values()),
        })
class UserOrderCountsView(APIView):
    """
    GET /api/v1/bill/user/order-counts/
    个人中心徽章:返回当前用户各状态订单数(商品+服务合并)
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def get(self, request):
        user = request.user

        # ── 商品订单 ──
        p_qs = ProductOrder.objects.filter(user=user, user_deleted=False)

        p_pending_pay = p_qs.filter(
            status=ProductOrder.Status.PENDING_PAYMENT,
        ).count()

        p_pending_use = p_qs.filter(status__in=[
            ProductOrder.Status.PAID,
            ProductOrder.Status.PENDING_SHIPMENT,
            ProductOrder.Status.SHIPPED,
            ProductOrder.Status.PENDING_PICKUP,
        ]).count()

        p_pending_review = p_qs.filter(
            status=ProductOrder.Status.COMPLETED,
            is_reviewed=False,
        ).count()

        # 退款售后徽章:只统计「处理中」的退款,已完成退款(REFUNDED)不再计入
        p_refund = p_qs.filter(
            status=ProductOrder.Status.REFUNDING,
        ).count()

        # ── 服务订单 ──
        s_qs = ServiceOrder.objects.filter(user=user, user_deleted=False)

        s_pending_pay = s_qs.filter(
            status=ServiceOrder.Status.PENDING_PAYMENT,
        ).count()

        s_pending_use = s_qs.filter(status__in=[
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_ACCEPT,
            ServiceOrder.Status.PENDING_ASSIGNMENT,
            ServiceOrder.Status.ASSIGNED,
            ServiceOrder.Status.IN_SERVICE,
            ServiceOrder.Status.PENDING_USE,
            ServiceOrder.Status.PENDING_DELIVERY,
            ServiceOrder.Status.DELIVERING,
        ]).count()

        s_pending_review = s_qs.filter(
            status=ServiceOrder.Status.COMPLETED,
            is_reviewed=False,
        ).count()

        # 退款售后徽章:只统计「处理中」的退款,已完成退款(REFUNDED)不再计入
        s_refund = s_qs.filter(
            status=ServiceOrder.Status.REFUNDING,
        ).count()

        return Response({
            'pending_payment': p_pending_pay + s_pending_pay,
            'pending_use': p_pending_use + s_pending_use,
            'pending_review': p_pending_review + s_pending_review,
            'refund': p_refund + s_refund,
        })

# ══════════════════════════════════════════════════════════════
# 商家端 - 统一核销码接口(自动判断商品/服务)
# ══════════════════════════════════════════════════════════════

# 商品订单状态分类
PRODUCT_PENDING_STATUSES = {'pending_shipment', 'pending_pickup', 'refunding', 'paid'}
PRODUCT_PICKUP_STATUSES = {'pending_pickup'}
PRODUCT_PROCESSING_STATUSES = {'shipped', 'received', 'verified'}
PRODUCT_FINISHED_STATUSES = {'completed', 'refunded', 'cancelled'}

# 服务订单状态分类
SERVICE_PENDING_STATUSES = {'pending_accept', 'pending_assignment', 'pending_use', 'pending_delivery', 'refunding', 'paid'}
SERVICE_PICKUP_STATUSES = {'pending_use'}
SERVICE_PROCESSING_STATUSES = {'assigned', 'in_service', 'verified', 'delivering', 'subscribing'}
SERVICE_FINISHED_STATUSES = {'completed', 'refunded', 'cancelled'}


class MerchantOrderStatsView(APIView):
    """
    商家端订单统计接口
    GET /api/v1/merchant/orders/stats/
    返回各分类订单数量
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def get(self, request):
        merchant_id = _get_merchant_id(request)
        # 商品订单统计
        product_qs = ProductOrder.objects.filter(merchant_id=merchant_id)
        product_pending = product_qs.filter(status__in=PRODUCT_PENDING_STATUSES).count()
        product_pickup = product_qs.filter(status__in=PRODUCT_PICKUP_STATUSES).count()
        product_processing = product_qs.filter(status__in=PRODUCT_PROCESSING_STATUSES).count()
        product_finished = product_qs.filter(status__in=PRODUCT_FINISHED_STATUSES).count()
        product_total = product_pending + product_pickup + product_processing + product_finished

        # 服务订单统计
        service_qs = ServiceOrder.objects.filter(merchant_id=merchant_id)
        service_pending = service_qs.filter(status__in=SERVICE_PENDING_STATUSES).count()
        service_pickup = service_qs.filter(status__in=SERVICE_PICKUP_STATUSES).count()
        service_processing = service_qs.filter(status__in=SERVICE_PROCESSING_STATUSES).count()
        service_finished = service_qs.filter(status__in=SERVICE_FINISHED_STATUSES).count()
        service_total = service_pending + service_pickup + service_processing + service_finished

        return Response({
            'product': {
                'pending': product_pending,
                'pickup': product_pickup,
                'processing': product_processing,
                'finished': product_finished,
                'total': product_total,
            },
            'service': {
                'pending': service_pending,
                'pickup': service_pickup,
                'processing': service_processing,
                'finished': service_finished,
                'total': service_total,
            },
            'all': {
                'pending': product_pending + service_pending,
                'pickup': product_pickup + service_pickup,
                'processing': product_processing + service_processing,
                'finished': product_finished + service_finished,
                'total': product_total + service_total,
            }
        })


class MerchantUnifiedVerifyView(APIView):
    """
    统一核销接口 — 商家扫码 / 输码,自动识别商品或服务订单。

    POST /api/v1/merchant/orders/verify-by-code/
    body: { verify_code: "12345678" }

    返回:
      成功:
        {
          "message": "核销成功",
          "order_type": "product" | "service",
          "order": { ...订单详情... }
        }
      失败:
        { "error": "核销码无效或已使用" }
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def post(self, request):
        code = (request.data.get('verify_code') or '').strip()
        if not code:
            return Response(
                {'error': '请输入核销码'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        merchant_id = _get_merchant_id(request)
        now = timezone.now()

        # ── 1. 先查服务订单 ──
        svc_active = [
            ServiceOrder.Status.PAID,
            ServiceOrder.Status.PENDING_USE,
            ServiceOrder.Status.ASSIGNED,
            ServiceOrder.Status.IN_SERVICE,
        ]
        svc_order = ServiceOrder.objects.filter(
            merchant_id=merchant_id,
            verify_code=code,
            verified_at__isnull=True,
            status__in=svc_active,
        ).first()

        if svc_order:
            return self._verify_service(request, svc_order, code, now)

        # ── 2. 再查商品订单 ──
        prod_active = [
            ProductOrder.Status.PAID,
            ProductOrder.Status.PENDING_PICKUP,
        ]
        prod_order = ProductOrder.objects.filter(
            merchant_id=merchant_id,
            verify_code=code,
            delivery_type=ProductOrder.DeliveryType.SELF_PICKUP,
            verified_at__isnull=True,
            status__in=prod_active,
        ).first()

        if prod_order:
            return self._verify_product(request, prod_order, code, now)

        # ── 3. 都没找到 ──
        # 友好提示:如果码存在但已核销/已退款,给出明确原因
        used = (
            ServiceOrder.objects.filter(
                merchant_id=merchant_id, verify_code=code,
                verified_at__isnull=False,
            ).exists()
            or ProductOrder.objects.filter(
                merchant_id=merchant_id, verify_code=code,
                verified_at__isnull=False,
            ).exists()
        )
        if used:
            return Response(
                {'error': '该核销码已使用'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {'error': '核销码无效'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ─── 服务订单核销 ───
    def _verify_service(self, request, order, code, now):
        # 过期检查
        if order.verify_expire_at and now > order.verify_expire_at:
            return Response(
                {'error': '核销码已过期'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            staff = getattr(request.user, 'staff', None)
            order.verify_order(by_staff=staff)
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        create_order_log(
            order.order_no, 'service', 'verify',
            request=request, operator_type='merchant',
            description=f'扫码核销 {code}',
        )

        # 统一核销入口的服务分支也同步微信订单中心。
        if order.status == ServiceOrder.Status.COMPLETED:
            _sync_wechat_order_center(
                order,
                logistics_type=4,  # 用户自提/线下交付
                scene='merchant_unified_verify_service',
            )

        # 推进完成钩子(销量+1 / 商家结算 / 发积分)
        if order.status == ServiceOrder.Status.COMPLETED:
            _on_order_completed(order, 'service')

        return Response({
            'message': '核销成功',
            'order_type': 'service',
            'order': MerchantServiceOrderDetailSerializer(order).data,
        })

    # ─── 商品订单核销 ───
    def _verify_product(self, request, order, code, now):
        # 过期检查
        if order.verify_expire_at and now > order.verify_expire_at:
            return Response(
                {'error': '核销码已过期,请联系平台处理'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 核销 → 直接完成
        order.status = ProductOrder.Status.COMPLETED
        order.verified_at = now
        order.completed_at = now
        update_fields = ['status', 'verified_at', 'completed_at', 'updated_at']

        staff = getattr(request.user, 'staff', None)
        if staff:
            order.verified_by_staff = staff
            update_fields.append('verified_by_staff')

        order.save(update_fields=update_fields)

        # 统一核销入口也必须同步微信自提信息；这是之前最容易漏掉的路径。
        _sync_wechat_order_center(
            order,
            logistics_type=4,  # 用户自提
            scene='merchant_unified_verify_product',
        )

        create_order_log(
            order.order_no, 'product', 'verify',
            request=request, operator_type='merchant',
            description=f'扫码核销 {code}',
        )

        # 推进完成钩子(销量+1 / 商家结算 / 发积分)
        _on_order_completed(order, 'product')

        return Response({
            'message': '核销成功',
            'order_type': 'product',
            'order': MerchantProductOrderDetailSerializer(order).data,
        })

class MerchantDashboardStatsView(APIView):
    """
    GET /api/v1/merchant/dashboard-stats/
    商户首页统计 — 一次返回所有首页卡片数据
      - today_orders        今日订单数(已付款的,商品+服务合并)
      - today_revenue       今日营业额(已完成订单 pay_amount 之和)
      - month_sales         本月销量(已完成订单数)
      - pending_shipment    待发货商品订单数(PAID + PENDING_SHIPMENT)
      - pending_assignment  待派单服务订单数(PAID + PENDING_ASSIGNMENT)
      - pending_accept      自动派单中的服务订单数
      - pending_total       上面三个的合计,前端 badge 用
      - breakdown           商品 / 服务拆分明细
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def get(self, request):
        merchant_id = _get_merchant_id(request)
        now = timezone.localtime(timezone.now())
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today_start.replace(day=1)

        # ── 今日订单数(剔除未付款和已取消)──
        prod_today_cnt = ProductOrder.objects.filter(
            merchant_id=merchant_id,
            created_at__gte=today_start,
        ).exclude(status__in=[
            ProductOrder.Status.PENDING_PAYMENT,
            ProductOrder.Status.CANCELLED,
        ]).count()

        svc_today_cnt = ServiceOrder.objects.filter(
            merchant_id=merchant_id,
            created_at__gte=today_start,
        ).exclude(status__in=[
            ServiceOrder.Status.PENDING_PAYMENT,
            ServiceOrder.Status.CANCELLED,
        ]).count()

        # ── 今日营业额(按完成时间)──
        prod_today_rev = ProductOrder.objects.filter(
            merchant_id=merchant_id,
            status=ProductOrder.Status.COMPLETED,
            completed_at__gte=today_start,
        ).aggregate(s=Sum('pay_amount'))['s'] or Decimal('0')

        svc_today_rev = ServiceOrder.objects.filter(
            merchant_id=merchant_id,
            status=ServiceOrder.Status.COMPLETED,
            completed_at__gte=today_start,
        ).aggregate(s=Sum('pay_amount'))['s'] or Decimal('0')

        # ── 本月销量 ──
        prod_month_cnt = ProductOrder.objects.filter(
            merchant_id=merchant_id,
            status=ProductOrder.Status.COMPLETED,
            completed_at__gte=month_start,
        ).count()
        svc_month_cnt = ServiceOrder.objects.filter(
            merchant_id=merchant_id,
            status=ServiceOrder.Status.COMPLETED,
            completed_at__gte=month_start,
        ).count()

        # ── 待处理(给浏览器通知用)──
        pending_shipment = ProductOrder.objects.filter(
            merchant_id=merchant_id,
            delivery_type=ProductOrder.DeliveryType.HOME_DELIVERY,
            status__in=[
                ProductOrder.Status.PAID,
                ProductOrder.Status.PENDING_SHIPMENT,
            ],
        ).count()
        pending_assignment = ServiceOrder.objects.filter(
            merchant_id=merchant_id,
            status__in=[
                ServiceOrder.Status.PAID,
                ServiceOrder.Status.PENDING_ASSIGNMENT,
            ],
        ).count()
        pending_accept = ServiceOrder.objects.filter(
            merchant_id=merchant_id,
            status=ServiceOrder.Status.PENDING_ACCEPT,
        ).count()

        today_revenue = (prod_today_rev + svc_today_rev).quantize(Decimal('0.01'))

        return Response({
            'today_orders': prod_today_cnt + svc_today_cnt,
            'today_revenue': str(today_revenue),
            'month_sales': prod_month_cnt + svc_month_cnt,
            'pending_shipment': pending_shipment,
            'pending_assignment': pending_assignment,
            'pending_accept': pending_accept,
            'pending_total': pending_shipment + pending_assignment + pending_accept,
            'breakdown': {
                'product_today_orders': prod_today_cnt,
                'service_today_orders': svc_today_cnt,
                'product_today_revenue': str(prod_today_rev.quantize(Decimal('0.01'))),
                'service_today_revenue': str(svc_today_rev.quantize(Decimal('0.01'))),
                'product_month_sales': prod_month_cnt,
                'service_month_sales': svc_month_cnt,
            },
            'updated_at': now.isoformat(),
        })

class MerchantDashboardView(APIView):
    """商家端数据看板统计接口"""
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    def get(self, request):
        merchant_id = _get_merchant_id(request)
        now = timezone.now()
        today = timezone.localdate()
        yesterday = today - timedelta(days=1)
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)

        # ───────────────────────── 订单统计 ─────────────────────────
        product_qs = ProductOrder.objects.filter(merchant_id=merchant_id)
        service_qs = ServiceOrder.objects.filter(merchant_id=merchant_id)
        paid_product = product_qs.filter(paid_at__isnull=False)
        paid_service = service_qs.filter(paid_at__isnull=False)

        # 各时间周期订单数
        orders = {
            'total': product_qs.count() + service_qs.count(),
            'today': product_qs.filter(created_at__date=today).count() + service_qs.filter(created_at__date=today).count(),
            'yesterday': product_qs.filter(created_at__date=yesterday).count() + service_qs.filter(created_at__date=yesterday).count(),
            'week': product_qs.filter(created_at__date__gte=week_start).count() + service_qs.filter(created_at__date__gte=week_start).count(),
            'month': product_qs.filter(created_at__date__gte=month_start).count() + service_qs.filter(created_at__date__gte=month_start).count(),
        }

        # ───────────────────────── 营收统计 ─────────────────────────
        def revenue_sum(qs, date_field=None, start=None):
            f = qs
            if date_field and start:
                f = f.filter(**{f'{date_field}__date__gte': start})
            return f.aggregate(s=Sum('pay_amount'))['s'] or Decimal('0')

        revenue = {
            'total': float((revenue_sum(paid_product) + revenue_sum(paid_service)).quantize(Decimal('0.01'))),
            'today': float((revenue_sum(paid_product, 'paid_at', today) + revenue_sum(paid_service, 'paid_at', today)).quantize(Decimal('0.01'))),
            'yesterday': float((revenue_sum(paid_product, 'paid_at', yesterday) + revenue_sum(paid_service, 'paid_at', yesterday)).quantize(Decimal('0.01'))),
            'week': float((revenue_sum(paid_product, 'paid_at', week_start) + revenue_sum(paid_service, 'paid_at', week_start)).quantize(Decimal('0.01'))),
            'month': float((revenue_sum(paid_product, 'paid_at', month_start) + revenue_sum(paid_service, 'paid_at', month_start)).quantize(Decimal('0.01'))),
        }
        # 客单价
        paid_total = paid_product.count() + paid_service.count()
        revenue['aov'] = round(revenue['total'] / paid_total, 2) if paid_total else 0.0
        # 退款金额
        refund_amount = (
            (product_qs.filter(status='refunded').aggregate(s=Sum('pay_amount'))['s'] or Decimal('0'))
            + (service_qs.filter(status='refunded').aggregate(s=Sum('pay_amount'))['s'] or Decimal('0'))
        )
        revenue['refund_amount'] = float(refund_amount.quantize(Decimal('0.01')))

        # ───────────────────────── 钱包统计 ─────────────────────────
        from wallet.models import MerchantWallet, MerchantWalletTransaction
        wallet = MerchantWallet.objects.filter(merchant_id=merchant_id).first()
        wallet_data = {
            'balance': float(wallet.balance.quantize(Decimal('0.01'))) if wallet else 0.0,
            'pending_settlement': float(wallet.pending_settlement.quantize(Decimal('0.01'))) if wallet else 0.0,
            'total_income': float(wallet.total_income.quantize(Decimal('0.01'))) if wallet else 0.0,
        }
        # 累计佣金支出
        commission_total = MerchantWalletTransaction.objects.filter(
            wallet__merchant_id=merchant_id,
            action=MerchantWalletTransaction.Action.COMMISSION_DEDUCT
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
        wallet_data['total_commission'] = float(abs(commission_total).quantize(Decimal('0.01')))

        # ───────────────────────── 待办提醒 ─────────────────────────
        todos = {
            'pending_shipment': product_qs.filter(status='pending_shipment').count(),
            'pending_pickup': product_qs.filter(status='pending_pickup').count(),
            'pending_accept': service_qs.filter(status__in=['pending_accept', 'pending_assignment']).count(),
            'pending_use': service_qs.filter(status='pending_use').count(),
            'refunding': product_qs.filter(status='refunding').count() + service_qs.filter(status='refunding').count(),
        }
        todos['total'] = sum(todos.values())

        # ───────────────────────── 近7天趋势 ─────────────────────────
        trend_start = today - timedelta(days=6)
        trend = []
        for i in range(7):
            d = trend_start + timedelta(days=i)
            p_cnt = product_qs.filter(created_at__date=d).count()
            s_cnt = service_qs.filter(created_at__date=d).count()
            p_rev = paid_product.filter(paid_at__date=d).aggregate(s=Sum('pay_amount'))['s'] or Decimal('0')
            s_rev = paid_service.filter(paid_at__date=d).aggregate(s=Sum('pay_amount'))['s'] or Decimal('0')
            trend.append({
                'date': d.isoformat(),
                'orders': p_cnt + s_cnt,
                'revenue': float((p_rev + s_rev).quantize(Decimal('0.01'))),
            })

        # ───────────────────────── 热销排行 ─────────────────────────
        from bill.models import ProductOrderItem, ServiceOrderItem
        # 商品热销top5
        hot_products = list(
            ProductOrderItem.objects.filter(order__merchant_id=merchant_id, order__status__in=['paid', 'completed', 'verified'])
            .values('product_id', 'product_name')
            .annotate(sales=Sum('quantity'))
            .order_by('-sales')[:5]
        )
        # 服务热销top5
        hot_services = list(
            ServiceOrderItem.objects.filter(order__merchant_id=merchant_id, order__status__in=['paid', 'completed', 'verified'])
            .values('service_id', 'service_name')
            .annotate(sales=Count('id'))
            .order_by('-sales')[:5]
        )

        return Response({
            'generated_at': now.isoformat(),
            'date': today.isoformat(),
            'orders': orders,
            'revenue': revenue,
            'wallet': wallet_data,
            'todos': todos,
            'trend_7d': trend,
            'hot_products': hot_products,
            'hot_services': hot_services,
        })
