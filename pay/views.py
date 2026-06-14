# -*- coding: utf-8 -*-
# pay/views.py

import logging
from decimal import Decimal, ROUND_DOWN

from django.db import transaction, IntegrityError
from django.db.models import Sum, F
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from rest_framework import viewsets, mixins, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action

from .models import PaymentOrder, PaymentRefund, generate_refund_no
from .serializers import (
    PaymentOrderListSerializer, PaymentOrderDetailSerializer,
    CreatePaymentSerializer, QueryPaymentSerializer,
    RefundListSerializer, RefundDetailSerializer,
    ApproveRefundSerializer, RejectRefundSerializer,
)

# 微信支付封装
from utils.wechat_pay import WeChatPayHelper

# 认证 / 权限
from utils.authentication import (
    UserAuthentication,
    MerchantOrSubAuthentication,
    ManagerAuthentication,
)
from utils.permission import (
    IsUser, IsMerchant, IsManager,
    get_merchant_id_from_request,
)


logger = logging.getLogger(__name__)

# 微信v2 回调成功 / 失败 响应
_WX_OK   = b'<xml><return_code><![CDATA[SUCCESS]]></return_code><return_msg><![CDATA[OK]]></return_msg></xml>'
_WX_FAIL = b'<xml><return_code><![CDATA[FAIL]]></return_code><return_msg><![CDATA[%s]]></return_msg></xml>'


# ══════════════════════════════════════════════════════════════
# 用户端 —— 支付单
# ══════════════════════════════════════════════════════════════

class PaymentOrderViewSet(mixins.ListModelMixin,
                          mixins.RetrieveModelMixin,
                          viewsets.GenericViewSet):
    """用户支付单(只读)"""
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]
    http_method_names      = ['get']

    def get_queryset(self):
        return (PaymentOrder.objects
                .filter(user_id=self.request.user.id)
                .order_by('-created_at'))

    def get_serializer_class(self):
        if self.action == 'list':
            return PaymentOrderListSerializer
        return PaymentOrderDetailSerializer


# ══════════════════════════════════════════════════════════════
# 用户端 —— 创建支付(调微信)
# ══════════════════════════════════════════════════════════════

class CreatePaymentView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]

    def post(self, request):
        ser = CreatePaymentSerializer(data=request.data, context={'request': request})
        ser.is_valid(raise_exception=True)

        with transaction.atomic():
            payment = ser.save()

        # 0 元订单短路
        if payment.amount_in_cents <= 0:
            return self._handle_zero_payment(payment)

        # 正常调微信下单
        helper = WeChatPayHelper()
        try:
            pay_params = helper.create_payment_order(
                openid=ser.validated_data.get('openid', ''),
                total_fee=payment.amount_in_cents,
                body=f'订单 {payment.order_no}',
                out_trade_no=payment.out_trade_no,
            )
        except Exception as e:
            logger.exception('调起微信支付失败 payment_no=%s', payment.payment_no)
            payment.status = 'failed'
            payment.callback_raw = f'create error: {e}'
            payment.save(update_fields=['status', 'callback_raw', 'updated_at'])
            return Response(
                {'error': f'调起微信支付失败: {e}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment.pay_params = pay_params
        payment.save(update_fields=['pay_params', 'updated_at'])

        return Response({
            'payment_no':   payment.payment_no,
            'out_trade_no': payment.out_trade_no,
            'pay_params':   pay_params,
        })

    def _handle_zero_payment(self, payment):
        """0 元支付:走完整成功钩子链"""
        try:
            with transaction.atomic():
                payment = PaymentOrder.objects.select_for_update().get(pk=payment.pk)
                if payment.status != 'pending':
                    return Response({
                        'payment_no':   payment.payment_no,
                        'out_trade_no': payment.out_trade_no,
                        'zero_payment': True,
                        'message':      '已支付',
                    })

                payment.mark_paid(
                    channel_trade_no=f'ZERO_{payment.payment_no}',
                    callback_raw='zero amount auto paid',
                )
                order = _advance_business_order_to_paid(payment)

            # 副作用放在主事务外,失败不影响 mark_paid
            if order:
                _run_payment_success_hooks(payment, order)
        except Exception as e:
            logger.exception('0 元支付处理失败 payment_no=%s', payment.payment_no)
            return Response(
                {'error': f'0 元订单处理失败: {e}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'payment_no':   payment.payment_no,
            'out_trade_no': payment.out_trade_no,
            'zero_payment': True,
            'message':      '已支付',
        })


# ══════════════════════════════════════════════════════════════
# 用户端 —— 查询支付
# ══════════════════════════════════════════════════════════════

class QueryPaymentView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]

    def post(self, request):
        ser = QueryPaymentSerializer(data=request.data, context={'request': request})
        ser.is_valid(raise_exception=True)
        return Response(PaymentOrderDetailSerializer(ser.payment).data)


# ══════════════════════════════════════════════════════════════
# 用户端 —— 自己的退款单
# ══════════════════════════════════════════════════════════════

class UserRefundViewSet(mixins.ListModelMixin,
                        mixins.RetrieveModelMixin,
                        viewsets.GenericViewSet):
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]
    http_method_names      = ['get']

    def get_queryset(self):
        return (PaymentRefund.objects
                .filter(user_id=self.request.user.id)
                .select_related('payment_order')
                .order_by('-created_at'))

    def get_serializer_class(self):
        if self.action == 'list':
            return RefundListSerializer
        return RefundDetailSerializer


# ══════════════════════════════════════════════════════════════
# 退款核心(商家 / 管理员共用)
# ══════════════════════════════════════════════════════════════

def _do_approve_refund(serializer, *, operator_type, operator_id, request_url=None):
    """审批同意:创建 PaymentRefund 并调微信发起退款。"""
    data = serializer.validated_data
    order       = data['_order']
    OrderModel  = data['_OrderModel']
    original    = data['_original']
    refund_amt  = data['refund_amount']
    reason      = data['reason']
    reason_text = data.get('reason_detail', '')

    with transaction.atomic():
        original = (PaymentOrder.objects
                    .select_for_update()
                    .get(pk=original.pk))

        refund_no = generate_refund_no()
        refund = PaymentRefund.objects.create(
            refund_no=refund_no,
            payment_order=original,
            order_no=order.order_no,
            user_id=original.user_id,
            refund_amount=refund_amt,
            reason=reason,
            reason_detail=reason_text,
            status='pending',
            operator_type=operator_type,
            operator_id=operator_id,
        )

    # 0 元订单退款:直接走回调流程,不调微信
    if str(original.channel_trade_no or '').startswith('ZERO_'):
        try:
            _handle_refund_callback({
                'out_refund_no': refund.refund_no,
                'refund_id': f'ZERO_{refund.refund_no}',
                'refund_status': 'SUCCESS',
            })
            refund.refresh_from_db()
        except Exception as e:
            logger.exception('0 元订单退款处理失败 refund_no=%s', refund.refund_no)
            return refund, f'0 元订单退款失败: {e}'
        return refund, None

    helper = WeChatPayHelper()
    try:
        result = helper.process_refund(
            transaction_id=original.channel_trade_no,
            out_refund_no=refund.refund_no,
            total_fee=original.amount_in_cents,
            refund_fee=refund.refund_amount_in_cents,
            reason=reason_text or refund.get_reason_display(),
        )
    except Exception as e:
        logger.exception('调微信退款失败 refund_no=%s', refund.refund_no)
        refund.mark_failed(callback_raw=f'apply error: {e}')
        return refund, f'微信退款发起失败: {e}'

    refund.callback_raw = str(result)
    refund.save(update_fields=['callback_raw', 'updated_at'])

    return refund, None


def _do_reject_refund(serializer, *, operator_type, operator_id):
    """审批拒绝:把订单状态从 REFUNDING 撤回。"""
    data = serializer.validated_data
    order        = data['_order']
    OrderModel   = data['_OrderModel']
    revert       = data['revert_status']
    reject_reason = data['reject_reason']

    with transaction.atomic():
        order = OrderModel.objects.select_for_update().get(pk=order.pk)
        if order.status != OrderModel.Status.REFUNDING:
            return None, f'订单状态已变为 {order.get_status_display()},无法拒绝'

        order.status = revert
        order.save(update_fields=['status', 'updated_at'])

    try:
        from bill.serializers import create_order_log
        create_order_log(
            order.order_no,
            'product' if OrderModel.__name__ == 'ProductOrder' else 'service',
            'refund_reject',
            operator_type=operator_type,
            description=f'拒绝退款: {reject_reason}',
        )
    except Exception:
        pass

    return order, None


# ══════════════════════════════════════════════════════════════
# 商家端 —— 退款审批
# ══════════════════════════════════════════════════════════════

class MerchantRefundViewSet(mixins.ListModelMixin,
                            mixins.RetrieveModelMixin,
                            viewsets.GenericViewSet):
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes     = [IsMerchant]

    def get_queryset(self):
        merchant_id = get_merchant_id_from_request(self.request)
        return (PaymentRefund.objects
                .filter(payment_order__merchant_id=merchant_id)
                .select_related('payment_order')
                .order_by('-created_at'))

    def get_serializer_class(self):
        if self.action == 'list':
            return RefundListSerializer
        return RefundDetailSerializer

    @action(detail=False, methods=['post'])
    def approve(self, request):
        merchant_id = get_merchant_id_from_request(request)
        operator_id = request.user.id

        ser = ApproveRefundSerializer(
            data=request.data,
            context={'request': request, 'merchant_id_filter': merchant_id},
            operator_type='merchant',
        )
        ser.is_valid(raise_exception=True)

        refund, err = _do_approve_refund(
            ser, operator_type='merchant', operator_id=operator_id,
        )
        if err:
            return Response({'error': err, 'refund_no': refund.refund_no},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': '退款已发起,等待微信处理',
            'refund':  RefundDetailSerializer(refund).data,
        })

    @action(detail=False, methods=['post'])
    def reject(self, request):
        merchant_id = get_merchant_id_from_request(request)
        operator_id = request.user.id

        ser = RejectRefundSerializer(
            data=request.data,
            context={'request': request, 'merchant_id_filter': merchant_id},
        )
        ser.is_valid(raise_exception=True)

        order, err = _do_reject_refund(
            ser, operator_type='merchant', operator_id=operator_id,
        )
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'message': '已拒绝退款,订单状态已撤回'})


# ══════════════════════════════════════════════════════════════
# 管理端 —— 退款审批
# ══════════════════════════════════════════════════════════════

class AdminRefundViewSet(mixins.ListModelMixin,
                         mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    authentication_classes = [ManagerAuthentication]
    permission_classes     = [IsManager]

    def get_queryset(self):
        return (PaymentRefund.objects
                .select_related('payment_order')
                .order_by('-created_at'))

    def get_serializer_class(self):
        if self.action == 'list':
            return RefundListSerializer
        return RefundDetailSerializer

    @action(detail=False, methods=['post'])
    def approve(self, request):
        ser = ApproveRefundSerializer(
            data=request.data,
            context={'request': request, 'merchant_id_filter': None},
            operator_type='admin',
        )
        ser.is_valid(raise_exception=True)

        refund, err = _do_approve_refund(
            ser, operator_type='admin', operator_id=request.user.id,
        )
        if err:
            return Response({'error': err, 'refund_no': refund.refund_no},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': '退款已发起',
            'refund':  RefundDetailSerializer(refund).data,
        })

    @action(detail=False, methods=['post'])
    def reject(self, request):
        ser = RejectRefundSerializer(
            data=request.data,
            context={'request': request, 'merchant_id_filter': None},
        )
        ser.is_valid(raise_exception=True)

        order, err = _do_reject_refund(
            ser, operator_type='admin', operator_id=request.user.id,
        )
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'message': '已拒绝退款,订单状态已撤回'})


# ══════════════════════════════════════════════════════════════
# 微信回调
# ══════════════════════════════════════════════════════════════

@csrf_exempt
@require_POST
def wechat_callback(request, callback_type):
    try:
        xml_data = request.body.decode('utf-8') if isinstance(request.body, bytes) else request.body
    except Exception:
        logger.exception('回调 body 解码失败')
        return HttpResponse(_WX_FAIL % b'decode error', content_type='application/xml')

    helper = WeChatPayHelper()
    try:
        data = helper.parse_callback(xml_data, callback_type)
    except Exception as e:
        logger.exception('微信回调解析失败 type=%s', callback_type)
        return HttpResponse(
            _WX_FAIL % f'parse error: {e}'.encode('utf-8'),
            content_type='application/xml',
        )

    if callback_type == 'payment':
        return _handle_payment_callback(data)
    elif callback_type == 'refund':
        return _handle_refund_callback(data)

    return HttpResponse(_WX_FAIL % b'unknown type', content_type='application/xml')


def _handle_payment_callback(data):
    out_trade_no   = data.get('out_trade_no')
    transaction_id = data.get('transaction_id', '')
    return_code    = data.get('return_code')
    result_code    = data.get('result_code')

    if not out_trade_no:
        return HttpResponse(_WX_FAIL % b'missing out_trade_no', content_type='application/xml')

    order_to_run_hooks = None
    payment_for_hooks = None

    try:
        with transaction.atomic():
            payment = (PaymentOrder.objects
                       .select_for_update()
                       .get(out_trade_no=out_trade_no))

            if payment.status == 'paid':
                return HttpResponse(_WX_OK, content_type='application/xml')

            if return_code == 'SUCCESS' and result_code == 'SUCCESS':
                payment.mark_paid(
                    channel_trade_no=transaction_id,
                    callback_raw=str(data),
                )
                order = _advance_business_order_to_paid(payment)
                if order:
                    order_to_run_hooks = order
                    payment_for_hooks = payment
            else:
                payment.status = 'failed'
                payment.callback_raw = str(data)
                payment.save(update_fields=['status', 'callback_raw', 'updated_at'])

    except PaymentOrder.DoesNotExist:
        logger.error('回调命中不存在的支付单 out_trade_no=%s', out_trade_no)
        return HttpResponse(_WX_FAIL % b'payment not found', content_type='application/xml')
    except Exception:
        logger.exception('处理支付回调异常 out_trade_no=%s', out_trade_no)
        return HttpResponse(_WX_FAIL % b'internal error', content_type='application/xml')

    # 主事务已提交,跑副作用钩子(钩子失败不影响回调返回)
    if order_to_run_hooks:
        _run_payment_success_hooks(payment_for_hooks, order_to_run_hooks)

    return HttpResponse(_WX_OK, content_type='application/xml')


def _handle_refund_callback(data):
    out_refund_no = data.get('out_refund_no')
    refund_id     = data.get('refund_id', '')
    refund_status = data.get('refund_status')

    if not out_refund_no:
        return HttpResponse(_WX_FAIL % b'missing out_refund_no', content_type='application/xml')

    order_to_run_hooks = None
    refund_for_hooks = None

    try:
        with transaction.atomic():
            refund = (PaymentRefund.objects
                      .select_for_update()
                      .select_related('payment_order')
                      .get(refund_no=out_refund_no))

            if refund.status in ('success', 'failed'):
                return HttpResponse(_WX_OK, content_type='application/xml')

            if refund_status == 'SUCCESS':
                refund.mark_success(
                    channel_refund_no=refund_id,
                    callback_raw=str(data),
                )
                order = _advance_business_order_to_refunded(refund)
                if order:
                    order_to_run_hooks = order
                    refund_for_hooks = refund
            else:
                refund.mark_failed(callback_raw=str(data))

    except PaymentRefund.DoesNotExist:
        logger.error('退款回调命中不存在的退款单 out_refund_no=%s', out_refund_no)
        return HttpResponse(_WX_FAIL % b'refund not found', content_type='application/xml')
    except Exception:
        logger.exception('处理退款回调异常 out_refund_no=%s', out_refund_no)
        return HttpResponse(_WX_FAIL % b'internal error', content_type='application/xml')

    # 主事务已提交,跑副作用钩子
    if order_to_run_hooks:
        _run_refund_success_hooks(refund_for_hooks, order_to_run_hooks)

    return HttpResponse(_WX_OK, content_type='application/xml')


# ══════════════════════════════════════════════════════════════
# 业务订单状态推进
# ══════════════════════════════════════════════════════════════

def _advance_business_order_to_paid(payment):
    """支付成功后推进业务订单状态。"""
    # ── 充值订单 ──
    if payment.order_type == 'recharge':
        try:
            from wallet.models import WalletRecharge
            recharge = WalletRecharge.objects.filter(recharge_no=payment.order_no).first()
            if not recharge:
                return None
            if recharge.status == WalletRecharge.Status.PENDING:
                recharge.status = WalletRecharge.Status.PAID
                recharge.paid_at = timezone.now()
                recharge.save(update_fields=['status', 'paid_at', 'updated_at'])
            return recharge
        except Exception:
            logger.exception('推进充值订单状态失败 order_no=%s', payment.order_no)
            return None

    # ── 商品 / 服务订单 ──
    try:
        if payment.order_type == 'product':
            from bill.models import ProductOrder
            OrderModel = ProductOrder
        else:
            from bill.models import ServiceOrder
            OrderModel = ServiceOrder

        order = OrderModel.objects.filter(order_no=payment.order_no).first()
        if not order:
            return None

        if order.status != OrderModel.Status.PENDING_PAYMENT:
            return order

        update_fields = ['status', 'updated_at']

        is_walk_in = (
            payment.order_type == 'service'
            and getattr(order, 'service_type', '') == 'walk_in'
        )
        is_product_pickup = (
            payment.order_type == 'product'
            and getattr(order, 'delivery_type', '') == 'self_pickup'
        )

        if is_walk_in:
            from bill.models import generate_unique_verify_code
            from datetime import timedelta

            order.status = OrderModel.Status.PENDING_USE
            try:
                order.verify_code = generate_unique_verify_code(order.merchant_id)
                update_fields.append('verify_code')
            except RuntimeError:
                logger.exception('生成核销码失败 order_no=%s', payment.order_no)
            order.verify_expire_at = timezone.now() + timedelta(days=90)
            update_fields.append('verify_expire_at')

        elif is_product_pickup:
            from bill.models import generate_unique_verify_code
            from datetime import timedelta

            order.status = OrderModel.Status.PENDING_PICKUP
            try:
                order.verify_code = generate_unique_verify_code(order.merchant_id)
                update_fields.append('verify_code')
            except RuntimeError:
                logger.exception('生成自提核销码失败 order_no=%s', payment.order_no)
            order.verify_expire_at = timezone.now() + timedelta(days=7)
            update_fields.append('verify_expire_at')
            if hasattr(order, 'pickup_deadline'):
                order.pickup_deadline = order.verify_expire_at
                update_fields.append('pickup_deadline')

        else:
            order.status = OrderModel.Status.PAID

        if hasattr(order, 'paid_at'):
            order.paid_at = timezone.now()
            update_fields.append('paid_at')

        order.save(update_fields=update_fields)
        return order

    except Exception:
        logger.exception('推进业务订单状态失败 order_no=%s', payment.order_no)
        return None


def _advance_business_order_to_refunded(refund):
    """
    退款成功后推进业务订单状态。

    规则:
      - 累计退款 >= 原支付金额 → REFUNDED(全额退完)
      - 累计退款 < 原支付金额  → 部分退款,订单不应停在 REFUNDING:
            * 商品/服务订单一律推到 CANCELLED
            * 释放排班资源(服务订单)
            * 不返还券、不返还金币(语义:消费已发生)
    """
    try:
        order_type = refund.payment_order.order_type
        if order_type == 'product':
            from bill.models import ProductOrder
            OrderModel = ProductOrder
        elif order_type == 'service':
            from bill.models import ServiceOrder
            OrderModel = ServiceOrder
        else:
            # 充值订单的退款,这里不处理订单状态
            return None

        order = OrderModel.objects.filter(order_no=refund.order_no).first()
        if not order:
            return None

        total_refunded = (PaymentRefund.objects
                          .filter(payment_order=refund.payment_order, status='success')
                          .aggregate(s=Sum('refund_amount'))['s'] or Decimal('0'))

        # ────── 全额退款 ──────
        if total_refunded >= refund.payment_order.amount:
            if order.status != OrderModel.Status.REFUNDED:
                order.status = OrderModel.Status.REFUNDED
                order.save(update_fields=['status', 'updated_at'])

                if order_type == 'service' and getattr(order, 'service_type', '') == 'scheduled':
                    try:
                        from bill.models import DeliverySchedule
                        pending_schedules = DeliverySchedule.objects.filter(
                            order=order,
                        ).exclude(status__in=[
                            DeliverySchedule.Status.COMPLETED,
                            DeliverySchedule.Status.CANCELLED,
                        ])
                        for sch in pending_schedules:
                            sch.cancel(reason='订单退款,批量取消')
                            # 同时释放已分配员工的时段
                            if sch.assigned_staff_id:
                                from bill.models import _cancel_staff_time_slot
                                # 注意:DeliverySchedule 没有 staff_time_slot 直接关联,
                                # 取决于派单时是否创建了 StaffTimeSlot
                                pass
                    except Exception:
                        logger.exception('取消周期配送子记录失败 order_no=%s', refund.order_no)

                # 退还优惠券
                try:
                    from bill.serializers import return_coupon
                    return_coupon(order)
                except Exception:
                    logger.exception(
                        '退款退还优惠券失败 order_no=%s', refund.order_no,
                    )

                # 销量回滚(savepoint 隔离)
                try:
                    from bill.views import _on_order_refunded
                    with transaction.atomic():
                        _on_order_refunded(order, order_type)
                except Exception:
                    logger.exception(
                        '回调销量回滚失败 order_no=%s', refund.order_no,
                    )
            return order

        # ────── 部分退款 ──────
        # 订单不应停在 REFUNDING,推到 CANCELLED(违约取消已结算)
        if order.status == OrderModel.Status.REFUNDING:
            order.status = OrderModel.Status.CANCELLED
            if not order.cancel_reason:
                order.cancel_reason = (
                    f'部分退款 ¥{refund.refund_amount} 完成,扣下部分留作违约金'
                )
            order.save(update_fields=[
                'status', 'cancel_reason', 'updated_at',
            ])

            # 服务订单:释放排班资源
            if order_type == 'service':
                try:
                    from bill.views import _release_time_slot
                    _release_time_slot(order)
                except Exception:
                    logger.exception(
                        '部分退款释放时段失败 order_no=%s', refund.order_no,
                    )

            # 部分退不退券、不返金币、不回滚销量
            # (订单还没到 COMPLETED 状态,销量本来就没 +1;
            #  券在违约场景下视为已消费,留给商家)
        return order

    except Exception:
        logger.exception(
            '推进业务订单退款状态失败 order_no=%s', refund.order_no,
        )
        return None

# ══════════════════════════════════════════════════════════════
# 支付成功钩子链(各副作用彼此独立,互不连累)
# ══════════════════════════════════════════════════════════════

def _run_payment_success_hooks(payment, order):
    """
    支付成功的所有副作用 —— 每个独立 atomic,任何一个失败不影响其他。
    在主事务之外调用。
    """
    # 1) 扣用户金币抵扣(订单类型)
    if payment.order_type in ('product', 'service'):
        _hook_deduct_user_coins(payment, order)

    # 2) 充值入账
    if payment.order_type == 'recharge':
        _hook_recharge_grant(payment, order)
        return  # 充值不需要后续步骤

    # 3) 商家待结算入账
    _hook_merchant_pending_in(payment, order)

    # 4) 触发自动派单(服务订单)
    if payment.order_type == 'service':
        _hook_trigger_dispatch(order)

    # 5) 活动金币(支付时发用户 + 发商家并冻结)
    _hook_grant_activity_on_pay(payment, order)


def _hook_deduct_user_coins(payment, order):
    """扣减用户金币抵扣"""
    coins = getattr(order, 'coins_deducted', 0) or 0
    if coins <= 0:
        return
    try:
        from wallet.models import UserWallet, WalletTransaction
        with transaction.atomic():
            user_wallet, _ = UserWallet.objects.get_or_create(user_id=order.user_id)
            user_wallet.change_gold(
                amount=-coins,
                action=WalletTransaction.Action.GOLD_DEDUCT,
                operator_id=order.user_id,
                operator_role='user',
                related_type=f'{payment.order_type}_order',
                related_id=order.id,
                remark=f'订单 {order.order_no} 金币抵扣',
                idempotent_key=f'order_coin_deduct_{order.order_no}',
            )
    except Exception:
        logger.exception('扣减用户金币失败 order_no=%s', order.order_no)


def _hook_merchant_pending_in(payment, order):
    """商家入待结算"""
    merchant_id = getattr(order, 'merchant_id', None)
    if not merchant_id or payment.amount <= 0:
        return
    try:
        from wallet.models import MerchantWallet, MerchantWalletTransaction
        with transaction.atomic():
            mw = MerchantWallet.objects.filter(merchant_id=merchant_id).first()
            if not mw:
                logger.error('商家钱包不存在 merchant_id=%s', merchant_id)
                return
            mw.change_pending(
                amount=payment.amount,
                action=MerchantWalletTransaction.Action.PENDING_IN,
                operator_role='system',
                related_order_no=order.order_no,
                related_type=f'{payment.order_type}_order',
                related_id=order.id,
                remark=f'订单 {order.order_no} 入账',
                idempotent_key=f'order_pending_in_{payment.payment_no}',
            )
    except Exception:
        logger.exception('商家入待结算失败 order_no=%s', order.order_no)


def _hook_trigger_dispatch(order):
    """触发服务订单的自动派单(过滤掉不适合的类型)"""
    # 商家协商型预约:让商家手动派,不要系统抢
    if (order.service_type == 'appointment'
            and getattr(order, 'schedule_type', '') == 'merchant'):
        # 直接置为待派单,商家进 admin 处理
        try:
            with transaction.atomic():
                from bill.models import ServiceOrder
                locked = ServiceOrder.objects.select_for_update().get(pk=order.pk)
                if locked.status == ServiceOrder.Status.PAID:
                    locked.status = ServiceOrder.Status.PENDING_ASSIGNMENT
                    locked.save(update_fields=['status', 'updated_at'])
        except Exception:
            logger.exception('置为待派单失败 order_no=%s', order.order_no)
        return

    try:
        from bill.tasks import task_try_auto_dispatch
        task_try_auto_dispatch.delay(order.id)
        logger.info('已注册自动派单任务 order_no=%s', order.order_no)
    except Exception:
        logger.exception('注册自动派单钩子失败 order_no=%s', order.order_no)


def _hook_recharge_grant(payment, recharge):
    """充值入金币 —— 面额 + 锁定的活动加送"""
    try:
        _grant_recharge_coins(payment, recharge)
    except Exception:
        logger.exception('充值入账失败 payment_no=%s', payment.payment_no)


def _hook_grant_activity_on_pay(payment, order):
    """订单消费送活动金币(择优)"""
    try:
        _grant_activity_on_pay(payment, order)
    except Exception:
        logger.exception('活动钩子失败 payment_no=%s', payment.payment_no)


# ══════════════════════════════════════════════════════════════
# 退款成功钩子链
# ══════════════════════════════════════════════════════════════

def _run_refund_success_hooks(refund, order):
    """退款成功的所有副作用 —— 每个独立 atomic。"""
    # 充值订单的退款逻辑暂不涉及(没有商家、没有活动金币撤销),如有需要再加
    if refund.payment_order.order_type == 'recharge':
        return

    # 1) 商家扣钱
    _hook_merchant_refund_deduct(refund, order)

    # 2) 按比例返还用户金币抵扣
    _hook_return_user_coins(refund, order)

    # 3) 撤销已发积分
    _hook_revoke_points(refund, order)

    # 4) 撤销/部分撤销活动金币
    _hook_revoke_activity_grants(refund, order)


def _hook_merchant_refund_deduct(refund, order):
    """商家退款扣回"""
    if not order.merchant_id:
        return
    try:
        from wallet.models import MerchantWallet, MerchantWalletTransaction
        payment = refund.payment_order
        OrderModel = type(order)
        A = MerchantWalletTransaction.Action

        completed_states = {OrderModel.Status.COMPLETED}
        if hasattr(OrderModel.Status, 'RECEIVED'):
            completed_states.add(OrderModel.Status.RECEIVED)
        if hasattr(OrderModel.Status, 'VERIFIED'):
            completed_states.add(OrderModel.Status.VERIFIED)
        already_settled = order.status in completed_states

        with transaction.atomic():
            mw = MerchantWallet.objects.filter(merchant_id=order.merchant_id).first()
            if not mw:
                logger.error('商家钱包不存在 merchant_id=%s', order.merchant_id)
                return

            if already_settled:
                mw.change_balance(
                    amount=-refund.refund_amount,
                    action=A.REFUND_DEDUCT,
                    operator_role='system',
                    related_order_no=order.order_no,
                    related_type=f'{payment.order_type}_order',
                    related_id=order.id,
                    remark=f'订单 {order.order_no} 退款扣回',
                    idempotent_key=f'order_refund_deduct_{refund.refund_no}',
                    allow_negative=True,
                )
            else:
                mw.change_pending(
                    amount=-refund.refund_amount,
                    action=A.PENDING_DEDUCT,
                    operator_role='system',
                    related_order_no=order.order_no,
                    related_type=f'{payment.order_type}_order',
                    related_id=order.id,
                    remark=f'订单 {order.order_no} 退款扣回(待结算)',
                    idempotent_key=f'order_refund_pending_deduct_{refund.refund_no}',
                )
    except Exception:
        logger.exception('商家退款扣回失败 refund_no=%s', refund.refund_no)


def _hook_return_user_coins(refund, order):
    """按比例返还用户金币抵扣"""
    coins = getattr(order, 'coins_deducted', 0) or 0
    payment = refund.payment_order
    if coins <= 0 or payment.amount <= 0:
        return
    try:
        from wallet.models import UserWallet, WalletTransaction
        with transaction.atomic():
            ratio = Decimal(refund.refund_amount) / Decimal(payment.amount)
            return_coins = int(
                (Decimal(coins) * ratio).to_integral_value(rounding=ROUND_DOWN)
            )
            if return_coins <= 0:
                return
            user_wallet, _ = UserWallet.objects.get_or_create(user_id=order.user_id)
            user_wallet.change_gold(
                amount=return_coins,
                action=WalletTransaction.Action.GOLD_GRANT,
                operator_role='system',
                related_type=f'{payment.order_type}_order',
                related_id=order.id,
                remark=f'订单 {order.order_no} 退款返还金币',
                idempotent_key=f'order_refund_coin_return_{refund.refund_no}',
            )
    except Exception:
        logger.exception('退款返还金币失败 refund_no=%s', refund.refund_no)


def _hook_revoke_points(refund, order):
    """撤销已发的订单完成奖励积分"""
    try:
        from wallet.models import WalletTransaction
        ikey = f'order_points_reward_{order.order_no}'
        tx = WalletTransaction.objects.filter(
            idempotent_key=ikey,
            status=WalletTransaction.Status.NORMAL,
        ).first()
        if tx:
            tx.wallet.reverse_transaction(
                tx,
                reason=f'订单 {order.order_no} 退款撤销积分奖励',
                operator_role='system',
            )
    except Exception:
        logger.exception('撤销积分失败 refund_no=%s', refund.refund_no)


def _hook_revoke_activity_grants(refund, order):
    try:
        _revoke_activity_grants_on_refund(refund, order)
    except Exception:
        logger.exception('撤销活动金币失败 refund_no=%s', refund.refund_no)


# ══════════════════════════════════════════════════════════════
# 关闭支付单
# ══════════════════════════════════════════════════════════════

class ClosePaymentView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes     = [IsUser]

    def post(self, request):
        out_trade_no = request.data.get('out_trade_no')
        if not out_trade_no:
            return Response({'error': 'out_trade_no 必填'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            payment = PaymentOrder.objects.get(
                out_trade_no=out_trade_no, user_id=request.user.id,
            )
        except PaymentOrder.DoesNotExist:
            return Response({'error': '支付单不存在'},
                            status=status.HTTP_404_NOT_FOUND)

        if payment.status != 'pending':
            return Response({'message': 'ok'})

        with transaction.atomic():
            payment = PaymentOrder.objects.select_for_update().get(pk=payment.pk)
            if payment.status != 'pending':
                return Response({'message': 'ok'})
            payment.mark_closed()

            # ★ 联动取消业务订单
            self._cancel_business_order(payment)

        return Response({'message': 'ok'})

    def _cancel_business_order(self, payment):
        """关单时一并取消业务订单,释放资源"""
        if payment.order_type == 'product':
            from bill.models import ProductOrder
            OrderModel = ProductOrder
        elif payment.order_type == 'service':
            from bill.models import ServiceOrder
            OrderModel = ServiceOrder
        else:
            return  # 充值订单不处理

        order = OrderModel.objects.filter(order_no=payment.order_no).first()
        if not order or order.status != OrderModel.Status.PENDING_PAYMENT:
            return

        order.status = OrderModel.Status.CANCELLED
        order.cancel_reason = '用户主动关闭支付'
        order.save(update_fields=['status', 'cancel_reason', 'updated_at'])

        # 释放预约时段(服务订单)
        if payment.order_type == 'service':
            try:
                from bill.views import _release_time_slot
                _release_time_slot(order)
            except Exception:
                logger.exception('关单时释放时段失败 order_no=%s', order.order_no)

        # 退还优惠券
        try:
            from bill.serializers import return_coupon
            return_coupon(order)
        except Exception:
            logger.exception('关单时退券失败 order_no=%s', order.order_no)


# ══════════════════════════════════════════════════════════════
# 充值 —— 工具:挑选最佳活动(下单和回调都用)
# ══════════════════════════════════════════════════════════════

def pick_best_recharge_activity(user_id, amount):
    """
    挑选当前用户充值 amount 时奖励最高的活动。
    返回 (activity_or_None, bonus_coins)。
    下单时调用一次,把结果锁到 WalletRecharge 里;回调时按锁定值发。
    """
    from promotions.models import PaymentActivity

    activities = PaymentActivity.objects.filter(
        activity_type=PaymentActivity.ActivityType.RECHARGE,
        status=PaymentActivity.Status.ACTIVE,
        user_reward_enabled=True,
    )
    best_act, best = None, 0
    for act in activities:
        if not act.is_runnable():
            continue
        if act.per_user_limit > 0 and not act.user_can_take_more(user_id):
            continue
        r = act.calc_user_reward(amount)
        if r > best:
            best_act, best = act, r
    return best_act, best


# ══════════════════════════════════════════════════════════════
# 充值入金 —— 按下单时锁定的活动发
# ══════════════════════════════════════════════════════════════

def _grant_recharge_coins(payment, recharge):
    """
    充值到账:
      1) 面额金币(必发)
      2) 按 recharge.activity_id / bonus_coins 发活动加送(如有)

    activity_id / bonus_coins 是下单时锁定的,这里不重新挑活动。
    """
    from wallet.models import UserWallet, WalletTransaction
    from promotions.models import PaymentActivity, ActivityUserGrant

    # 1) 面额金币(自己一个原子)
    try:
        with transaction.atomic():
            if recharge.face_coins > 0:
                user_wallet, _ = UserWallet.objects.get_or_create(user_id=recharge.user_id)
                user_wallet.change_gold(
                    amount=recharge.face_coins,
                    action=WalletTransaction.Action.GOLD_GRANT,
                    operator_role='system',
                    related_type='wallet_recharge',
                    related_id=recharge.id,
                    remark=f'充值 ¥{recharge.amount}',
                    idempotent_key=f'recharge_face_{recharge.recharge_no}',
                )
    except Exception:
        logger.exception('充值面额金币入账失败 recharge=%s', recharge.recharge_no)
        # 面额都失败的话,后面活动加送也不要发了
        return

    # 2) 活动加送(自己一个原子,失败不影响面额)
    if not (recharge.activity_id and recharge.bonus_coins > 0):
        return

    try:
        act = PaymentActivity.objects.get(pk=recharge.activity_id)
    except PaymentActivity.DoesNotExist:
        logger.warning('充值活动已删除 recharge=%s act=%s',
                       recharge.recharge_no, recharge.activity_id)
        return

    try:
        with transaction.atomic():
            # 抢预算
            if not act.try_consume_user_budget(recharge.bonus_coins):
                logger.warning('充值活动预算已满,不发加送 recharge=%s',
                               recharge.recharge_no)
                return

            try:
                grant = ActivityUserGrant.objects.create(
                    activity=act,
                    user_id=recharge.user_id,
                    payment_no=payment.payment_no,
                    order_no=recharge.recharge_no,
                    trigger_amount=recharge.amount,
                    reward_coins=recharge.bonus_coins,
                )
            except IntegrityError:
                # 已发过(同 payment_no 重复回调)
                act.refund_user_budget(recharge.bonus_coins)
                return

            user_wallet, _ = UserWallet.objects.get_or_create(user_id=recharge.user_id)
            user_wallet.change_gold(
                amount=recharge.bonus_coins,
                action=WalletTransaction.Action.GOLD_GRANT,
                operator_role='system',
                related_type='activity_user_grant',
                related_id=grant.id,
                remark=f'充值活动「{act.name}」加送',
                idempotent_key=f'recharge_bonus_{grant.id}',
            )
    except Exception:
        logger.exception('充值活动加送失败 recharge=%s', recharge.recharge_no)


# ══════════════════════════════════════════════════════════════
# 订单消费送活动金币 —— 择优,各活动独立 atomic
# ══════════════════════════════════════════════════════════════

class _BudgetExceeded(Exception):
    """内部信号,用于触发 atomic 回滚 per_user_limit 校验"""
    pass


def _grant_activity_on_pay(payment, order):
    """
    订单支付成功 → 在所有可参与活动里挑奖励最高的发:
      - 用户奖励:择优一个
      - 商家奖励:择优一个
    用户/商家奖励彼此独立,且都各自一个 atomic,互不影响。
    """
    from promotions.models import PaymentActivity

    candidates = PaymentActivity.objects.filter(
        activity_type=PaymentActivity.ActivityType.ORDER_SPEND,
        status=PaymentActivity.Status.ACTIVE,
    )

    best_user_act, best_user_reward = None, 0
    best_merch_act, best_merch_reward = None, 0

    for act in candidates:
        if not act.is_runnable():
            continue
        if not act.supports_order_type(payment.order_type):
            continue
        if not act.is_merchant_eligible(order.merchant_id):
            continue
        if act.per_user_limit > 0 and not act.user_can_take_more(order.user_id):
            continue
        # ★ 用了金币抵扣 → 本单不参与活动,用户和商家奖励一并跳过
        if act.skip_for_coin_deduction(getattr(order, 'coins_deducted', 0)):
            continue

        if act.user_reward_enabled:
            r = act.calc_user_reward(payment.amount)
            if r > best_user_reward:
                best_user_act, best_user_reward = act, r

        if act.merchant_reward_enabled:
            r = act.calc_merchant_reward(payment.amount)
            if r > best_merch_reward:
                best_merch_act, best_merch_reward = act, r

    if best_user_act and best_user_reward > 0:
        try:
            _try_grant_user(best_user_act, order, payment, best_user_reward)
        except Exception:
            logger.exception('发用户活动金币失败 act=%s order=%s',
                             best_user_act.id, order.order_no)

    if best_merch_act and best_merch_reward > 0:
        try:
            _grant_merchant_earn(best_merch_act, payment, order)
        except Exception:
            logger.exception('发商家活动金币失败 act=%s order=%s',
                             best_merch_act.id, order.order_no)


def _try_grant_user(act, order, payment, reward):
    """
    给用户发活动金币,全原子。
    - 抢全局预算 (try_consume_user_budget)
    - 抢单人限额 (锁同活动同用户的 grant 行)
    - 真发币 (change_gold + ActivityUserGrant + Enrollment 统计)
    任何一步失败 → 全部回滚,预算自动归还。
    """
    from wallet.models import UserWallet, WalletTransaction
    from promotions.models import ActivityUserGrant, MerchantActivityEnrollment

    if reward <= 0:
        return

    try:
        with transaction.atomic():
            # 1) 抢预算
            if not act.try_consume_user_budget(reward):
                return  # 预算不够,放弃

            # 2) 创建 grant —— unique(activity, payment_no) 兜底
            try:
                grant = ActivityUserGrant.objects.create(
                    activity=act,
                    user_id=order.user_id,
                    merchant_id=getattr(order, 'merchant_id', None),
                    payment_no=payment.payment_no,
                    order_no=order.order_no,
                    trigger_amount=payment.amount,
                    reward_coins=reward,
                )
            except IntegrityError:
                # 同笔已发过,归还预算
                act.refund_user_budget(reward)
                return

            # 3) 校验单人限额(锁同活动同用户行)
            if act.per_user_limit > 0:
                taken = (ActivityUserGrant.objects
                         .select_for_update()
                         .filter(activity=act, user_id=order.user_id, is_revoked=False)
                         .count())
                if taken > act.per_user_limit:
                    raise _BudgetExceeded()

            # 4) 真发币
            user_wallet, _ = UserWallet.objects.get_or_create(user_id=order.user_id)
            user_wallet.change_gold(
                amount=reward,
                action=WalletTransaction.Action.GOLD_GRANT,
                operator_role='system',
                related_type='activity_user_grant',
                related_id=grant.id,
                remark=f'活动「{act.name}」奖励',
                idempotent_key=f'activity_user_grant_{grant.id}',
            )

            # 5) 商家报名统计(如有)
            merchant_id = getattr(order, 'merchant_id', None)
            if merchant_id:
                MerchantActivityEnrollment.objects.filter(
                    activity=act, merchant_id=merchant_id,
                ).update(
                    user_granted_count=F('user_granted_count') + 1,
                    user_granted_coins=F('user_granted_coins') + reward,
                )

    except _BudgetExceeded:
        # atomic 已回滚,无需手动归还预算(update 也被回滚)
        logger.info('用户超限,放弃发活动金币 act=%s user=%s',
                    act.id, order.user_id)


def _grant_merchant_earn(act, payment, order):
    """
    给商家发活动金币 + 冻结,全原子。
    - 抢全局预算
    - 创建 earn 记录
    - 钱包入账并冻结
    - 报名表统计
    任何一步失败 → 全部回滚。
    """
    from wallet.models import MerchantWallet, MerchantWalletTransaction
    from promotions.models import ActivityMerchantEarn, MerchantActivityEnrollment

    coins = act.calc_merchant_reward(payment.amount)
    if coins <= 0:
        return

    try:
        with transaction.atomic():
            # 1) 抢预算
            if not act.try_consume_merchant_budget(coins):
                return

            # 2) 创建 earn —— unique(activity, order_no) 兜底
            try:
                earn = ActivityMerchantEarn.objects.create(
                    activity=act,
                    merchant_id=order.merchant_id,
                    order_no=order.order_no,
                    order_type=payment.order_type,
                    trigger_amount=payment.amount,
                    earned_coins=coins,
                    frozen_status=ActivityMerchantEarn.FrozenStatus.FROZEN,
                )
            except IntegrityError:
                act.refund_merchant_budget(coins)
                return

            # 3) 钱包入账 + 冻结
            mw = MerchantWallet.objects.filter(merchant_id=order.merchant_id).first()
            if not mw:
                # 钱包应该已经在商家入驻时创建,这里没拿到说明数据异常
                logger.error('商家钱包不存在 merchant_id=%s', order.merchant_id)
                raise RuntimeError(f'merchant wallet missing: {order.merchant_id}')

            mw.change_gold(
                amount=coins,
                action=MerchantWalletTransaction.Action.GOLD_PROMOTION,
                operator_role='system',
                related_order_no=order.order_no,
                related_type='activity_merchant_earn',
                related_id=earn.id,
                remark=f'活动「{act.name}」商家奖励(订单完成后解冻)',
                idempotent_key=f'activity_merchant_earn_in_{earn.id}',
            )
            mw.freeze_gold(
                amount=coins,
                reason=f'活动「{act.name}」金币冻结,等待订单完成',
                operator_role='system',
                related_type='activity_merchant_earn',
                related_id=earn.id,
                idempotent_key=f'activity_merchant_earn_freeze_{earn.id}',
            )

            # 4) 报名表统计(如有)
            MerchantActivityEnrollment.objects.filter(
                activity=act, merchant_id=order.merchant_id,
            ).update(
                merchant_earned_coins=F('merchant_earned_coins') + coins,
            )

    except Exception:
        # atomic 回滚后(包括预算 update),记 log
        logger.exception('商家活动金币入账失败 act=%s order=%s',
                         act.id, order.order_no)


# ══════════════════════════════════════════════════════════════
# 订单完成时:解冻商家活动金币
# ══════════════════════════════════════════════════════════════

def _unfreeze_merchant_earns_on_complete(order):
    """
    订单完成 → 把所有还冻结的商家活动金币解冻。
    被 bill/views.py 的 _on_order_completed 调用。
    """
    from wallet.models import MerchantWallet
    from promotions.models import ActivityMerchantEarn

    earns = ActivityMerchantEarn.objects.filter(
        order_no=order.order_no,
        frozen_status=ActivityMerchantEarn.FrozenStatus.FROZEN,
    )
    if not earns.exists():
        return

    mw = MerchantWallet.objects.filter(merchant_id=order.merchant_id).first()
    if not mw:
        logger.error('商家钱包不存在,无法解冻 merchant_id=%s', order.merchant_id)
        return

    for earn in earns:
        try:
            with transaction.atomic():
                mw.unfreeze_gold(
                    amount=earn.earned_coins,
                    reason='订单完成,解冻活动金币',
                    operator_role='system',
                    related_type='activity_merchant_earn',
                    related_id=earn.id,
                    idempotent_key=f'activity_merchant_earn_unfreeze_{earn.id}',
                )
                earn.frozen_status = ActivityMerchantEarn.FrozenStatus.UNFROZEN
                earn.unfrozen_at = timezone.now()
                earn.save(update_fields=['frozen_status', 'unfrozen_at'])
        except Exception:
            logger.exception('解冻商家金币失败 earn_id=%s', earn.id)


# ══════════════════════════════════════════════════════════════
# 退款时:撤销活动金币(用户按比例,商家全额才撤)
# ══════════════════════════════════════════════════════════════

def _revoke_activity_grants_on_refund(refund, order):
    """
    退款撤销活动金币:
      - 用户金币:按比例撤(部分退也撤一部分)
      - 商家金币:仅全额退才撤;FROZEN 走零冲突路径,UNFROZEN 失败标记 REVOKE_PENDING

    用 ratio = refund_amount / payment.amount 计算撤回比例。
    """
    from wallet.models import (
        UserWallet, WalletTransaction,
        MerchantWallet, MerchantWalletTransaction,
    )
    from promotions.models import (
        ActivityUserGrant, ActivityMerchantEarn, PaymentActivity,
    )

    payment = refund.payment_order
    if payment.amount <= 0:
        return

    ratio = Decimal(refund.refund_amount) / Decimal(payment.amount)
    is_full = (refund.refund_amount >= payment.amount)

    # ───── 用户金币:按比例撤 ─────
    user_grants = ActivityUserGrant.objects.filter(
        payment_no=payment.payment_no, is_revoked=False,
    )
    for g in user_grants:
        revoke_coins = int(
            (Decimal(g.reward_coins) * ratio).to_integral_value(rounding=ROUND_DOWN)
        )
        if revoke_coins <= 0:
            continue

        try:
            with transaction.atomic():
                uw = UserWallet.objects.filter(user_id=g.user_id).first()
                if uw:
                    uw.change_gold(
                        amount=-revoke_coins,
                        action=WalletTransaction.Action.GOLD_DEDUCT,
                        operator_role='system',
                        related_type='payment_activity_revoke',
                        related_id=g.activity_id,
                        remark=(
                            f'退款撤销活动金币 {revoke_coins}'
                            + ('(全额)' if is_full else f'(按比例{ratio:.2%})')
                        ),
                        idempotent_key=f'aug_revoke_{refund.refund_no}_{g.id}',
                        allow_negative=True,
                    )

                if is_full:
                    g.is_revoked = True
                    g.revoked_at = timezone.now()
                    g.save(update_fields=['is_revoked', 'revoked_at'])
                else:
                    # 部分退:扣减 reward_coins,grant 仍有效
                    g.reward_coins = max(0, g.reward_coins - revoke_coins)
                    g.save(update_fields=['reward_coins'])

                # 归还活动预算
                try:
                    act = PaymentActivity.objects.get(pk=g.activity_id)
                    act.refund_user_budget(revoke_coins)
                except PaymentActivity.DoesNotExist:
                    pass
        except Exception:
            logger.exception('撤销用户活动金币失败 grant_id=%s', g.id)

    # ───── 商家金币:仅全额退款才撤 ─────
    if not is_full:
        return

    merchant_earns = ActivityMerchantEarn.objects.filter(
        order_no=order.order_no,
    ).exclude(frozen_status__in=[
        ActivityMerchantEarn.FrozenStatus.REVOKED,
        ActivityMerchantEarn.FrozenStatus.REVOKE_PENDING,
    ])

    for e in merchant_earns:
        mw = MerchantWallet.objects.filter(merchant_id=e.merchant_id).first()
        if not mw:
            # 钱包不存在 → 挂起
            ActivityMerchantEarn.objects.filter(pk=e.id).update(
                frozen_status=ActivityMerchantEarn.FrozenStatus.REVOKE_PENDING,
            )
            logger.error('钱包不存在,挂起撤销 earn_id=%s', e.id)
            continue

        try:
            with transaction.atomic():
                if e.frozen_status == ActivityMerchantEarn.FrozenStatus.FROZEN:
                    # 零冲突:先 unfreeze 再 deduct
                    mw.unfreeze_gold(
                        amount=e.earned_coins,
                        reason=f'退款撤销前解冻 earn_id={e.id}',
                        operator_role='system',
                        related_type='activity_merchant_earn',
                        related_id=e.id,
                        idempotent_key=f'amerch_unfreeze_for_revoke_{e.id}',
                    )
                    mw.change_gold(
                        amount=-e.earned_coins,
                        action=MerchantWalletTransaction.Action.GOLD_DEDUCT,
                        operator_role='system',
                        related_order_no=order.order_no,
                        related_type='payment_activity_revoke',
                        related_id=e.activity_id,
                        remark=f'订单退款撤销商家金币 {e.earned_coins}',
                        idempotent_key=f'amerch_revoke_{e.id}',
                    )
                else:
                    # UNFROZEN:可能商家已花。allow_negative=False 时会因 CheckConstraint 报错
                    # 这里不允许负数(保留约束),失败则挂起人工处理
                    mw.change_gold(
                        amount=-e.earned_coins,
                        action=MerchantWalletTransaction.Action.GOLD_DEDUCT,
                        operator_role='system',
                        related_order_no=order.order_no,
                        related_type='payment_activity_revoke',
                        related_id=e.activity_id,
                        remark=f'订单退款撤销(已解冻){e.earned_coins}',
                        idempotent_key=f'amerch_revoke_{e.id}',
                    )

                e.frozen_status = ActivityMerchantEarn.FrozenStatus.REVOKED
                e.is_revoked = True
                e.revoked_at = timezone.now()
                e.save(update_fields=['frozen_status', 'is_revoked', 'revoked_at'])

                # 归还活动预算
                try:
                    act = PaymentActivity.objects.get(pk=e.activity_id)
                    act.refund_merchant_budget(e.earned_coins)
                except PaymentActivity.DoesNotExist:
                    pass

        except Exception:
            logger.exception('撤销商家金币失败,挂起 earn_id=%s', e.id)
            # atomic 已回滚,用单独 update 把状态标记成 REVOKE_PENDING
            ActivityMerchantEarn.objects.filter(pk=e.id).update(
                frozen_status=ActivityMerchantEarn.FrozenStatus.REVOKE_PENDING,
            )