# -*- coding: utf-8 -*-
# @Time    : 2025/8/25 16:40
# @Author  : Delock

import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.http import HttpResponse
from rest_framework import status, generics, permissions, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from django_filters.rest_framework import DjangoFilterBackend
from wechatpy import WeChatPayException

from bill.models import Bill, ServiceOrder
from bill.serializers import (
    BillSerializer, BillCreateSerializer, ServiceOrderSerializer,
    ServiceOrderCreateSerializer, ServiceOrderUpdateSerializer,
    ServiceOrderSimpleSerializer
)
from bill.pagination import BillPagination, ServiceOrderPagination, SmallResultsSetPagination
from utils.authentication import UserAuthentication, AdminAuthentication
from utils.permission import IsOwnerOrAdmin, IsUserOwner
from utils.wechat_pay import WeChatPayHelper

logger = logging.getLogger(__name__)


class BillViewSet(ModelViewSet):
    """账单视图集"""

    queryset = Bill.objects.all()
    serializer_class = BillSerializer
    authentication_classes = [UserAuthentication, AdminAuthentication]
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]
    pagination_class = BillPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    # 过滤字段
    filterset_fields = {
        'transaction_type': ['exact'],
        'payment_method': ['exact'],
        'payment_status': ['exact'],
        'created_at': ['gte', 'lte', 'exact', 'date'],
        'amount': ['gte', 'lte'],
    }

    # 搜索字段
    search_fields = ['out_trade_no', 'wechat_transaction_id', 'description']

    # 排序字段
    ordering_fields = ['created_at', 'amount', 'payment_status']
    ordering = ['-created_at']

    def get_queryset(self):
        """根据用户类型过滤查询集"""
        user = self.request.user

        # 超级管理员可以查看所有账单
        if hasattr(user, '__class__') and user.__class__.__name__ == 'SuperAdmin':
            return Bill.objects.select_related('user').all()

        # 普通用户只能查看自己的账单
        return Bill.objects.select_related('user').filter(user=user)

    def get_serializer_class(self):
        """根据动作选择序列化器"""
        if self.action == 'create':
            return BillCreateSerializer
        return BillSerializer

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取账单统计信息"""
        queryset = self.get_queryset()

        # 总金额统计
        total_amount = queryset.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        # 按状态统计
        status_stats = queryset.values('payment_status').annotate(
            count=Count('id'),
            amount=Sum('amount')
        )

        # 按交易类型统计
        type_stats = queryset.values('transaction_type').annotate(
            count=Count('id'),
            amount=Sum('amount')
        )

        return Response({
            'total_amount': total_amount,
            'status_statistics': list(status_stats),
            'type_statistics': list(type_stats),
            'total_count': queryset.count()
        })

    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        """申请退款"""
        bill = self.get_object()

        # 检查是否可以退款
        if bill.transaction_type != 'payment':
            return Response(
                {'error': '只有付款记录可以申请退款'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if bill.payment_status != 'completed':
            return Response(
                {'error': '只有已完成的付款可以申请退款'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 检查是否已经有退款记录
        if Bill.objects.filter(
                wechat_transaction_id=bill.wechat_transaction_id,
                transaction_type='refund'
        ).exists():
            return Response(
                {'error': '该订单已申请过退款'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                # 调用微信退款接口
                pay_helper = WeChatPayHelper()
                refund_result = pay_helper.create_refund_order(
                    out_trade_no=bill.out_trade_no,
                    total_fee=int(bill.amount * 100),
                    refund_fee=int(bill.amount * 100),
                    refund_desc='用户申请退款'
                )

                # 创建退款记录
                refund_bill = Bill.objects.create(
                    out_trade_no=pay_helper.generate_out_trade_no(),
                    wechat_transaction_id=bill.wechat_transaction_id,
                    user=bill.user,
                    transaction_type='refund',
                    amount=bill.amount,
                    payment_method=bill.payment_method,
                    payment_status='pending',
                    description=f'退款：{bill.out_trade_no}'
                )

                return Response({
                    'message': '退款申请成功',
                    'refund_bill_id': refund_bill.id
                })

        except WeChatPayException as e:
            logger.error(f"退款申请失败: {e}")
            return Response(
                {'error': '退款申请失败，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ServiceOrderViewSet(ModelViewSet):
    """服务订单视图集"""

    queryset = ServiceOrder.objects.all()
    serializer_class = ServiceOrderSerializer
    authentication_classes = [UserAuthentication, AdminAuthentication]
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]
    pagination_class = ServiceOrderPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    # 过滤字段
    filterset_fields = {
        'status': ['exact'],
        'scheduled_date': ['gte', 'lte', 'exact'],
        'created_at': ['gte', 'lte', 'date'],
        'staff': ['exact'],
        'base_service': ['exact'],  # 新增:按基础服务过滤
        'total_price': ['gte', 'lte'],
    }

    # 搜索字段
    search_fields = ['service_address', 'contact_phone', 'customer_notes']

    # 排序字段
    ordering_fields = ['created_at', 'scheduled_date', 'total_price', 'status']
    ordering = ['-created_at']

    def get_queryset(self):
        """根据用户类型过滤查询集"""
        user = self.request.user

        # 超级管理员可以查看所有订单
        if hasattr(user, '__class__') and user.__class__.__name__ == 'SuperAdmin':
            return ServiceOrder.objects.select_related(
                'user', 'staff', 'bill', 'base_service'  # 新增预加载
            ).prefetch_related('pets', 'additional_services').all()  # 新增预加载

        # 普通用户只能查看自己的订单
        return ServiceOrder.objects.select_related(
            'user', 'staff', 'bill', 'base_service'  # 新增预加载
        ).prefetch_related('pets', 'additional_services').filter(user=user)  # 新增预加载

    def get_serializer_class(self):
        """根据动作选择序列化器"""
        if self.action == 'create':
            return ServiceOrderCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ServiceOrderUpdateSerializer
        elif self.action == 'list':
            return ServiceOrderSimpleSerializer
        return ServiceOrderSerializer

    def perform_create(self, serializer):
        """创建订单时设置用户并创建账单"""
        with transaction.atomic():
            # 先保存订单以计算价格(在serializer的create方法中已经计算)
            order = serializer.save(user=self.request.user)

            # 生成唯一订单号
            pay_helper = WeChatPayHelper()
            out_trade_no = pay_helper.generate_out_trade_no()

            # 创建账单
            bill = Bill.objects.create(
                out_trade_no=out_trade_no,
                user=self.request.user,
                transaction_type='payment',
                amount=order.total_price,
                payment_method='wechat',
                payment_status='pending',
                description=f'宠物服务订单 - {order.base_service.name}'
            )

            # 关联账单
            order.bill = bill
            order.save()

    @action(detail=False, methods=['get'])
    def my_orders(self, request):
        """获取我的订单（移动端友好）"""
        queryset = self.get_queryset().filter(user=request.user)

        # 使用小分页器
        self.pagination_class = SmallResultsSetPagination

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = ServiceOrderSimpleSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ServiceOrderSimpleSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """确认订单（管理员操作）"""
        order = self.get_object()

        if order.status != 'pending':
            return Response(
                {'error': '只能确认待确认的订单'},
                status=status.HTTP_400_BAD_REQUEST
            )

        staff_id = request.data.get('staff_id')
        if not staff_id:
            return Response(
                {'error': '请指定服务员工'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order.status = 'confirmed'
        order.staff_id = staff_id
        order.save()

        serializer = self.get_serializer(order)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """取消订单"""
        order = self.get_object()

        if order.status not in ['pending', 'confirmed']:
            return Response(
                {'error': '该订单无法取消'},
                status=status.HTTP_400_BAD_REQUEST
            )

        reason = request.data.get('reason', '')

        with transaction.atomic():
            order.status = 'cancelled'
            order.customer_notes = f"{order.customer_notes}\n取消原因：{reason}".strip()
            order.save()

            # 如果有关联的账单，需要处理退款
            if order.bill and order.bill.payment_status == 'completed':
                # 这里可以调用退款接口或创建退款记录
                pass

        serializer = self.get_serializer(order)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """获取订单统计信息"""
        queryset = self.get_queryset()

        # 按状态统计
        status_stats = queryset.values('status').annotate(
            count=Count('id'),
            total_amount=Sum('total_price')
        )

        # 按基础服务统计(新增)
        service_stats = queryset.values('base_service__name').annotate(
            count=Count('id'),
            total_amount=Sum('total_price')
        )

        # 总金额统计
        total_amount = queryset.aggregate(
            total=Sum('total_price')
        )['total'] or Decimal('0.00')

        # 今日订单数
        from django.utils import timezone
        today_orders = queryset.filter(
            created_at__date=timezone.now().date()
        ).count()

        return Response({
            'status_statistics': list(status_stats),
            'service_statistics': list(service_stats),  # 新增
            'total_amount': total_amount,
            'total_count': queryset.count(),
            'today_orders': today_orders
        })


# 保持原有的支付相关视图
def error_response(message, return_code='FAIL'):
    """统一的错误响应格式"""
    return HttpResponse(
        f'<xml><return_code><![CDATA[{return_code}]]></return_code>'
        f'<return_msg><![CDATA[{message}]]></return_msg></xml>'
    )


def handle_payment_callback(data):
    """处理支付回调逻辑"""
    out_trade_no = data.get('out_trade_no')
    transaction_id = data.get('transaction_id')
    trade_status = data.get('result_code')
    bill = None
    try:
        bill = Bill.objects.get(out_trade_no=out_trade_no, transaction_type='payment')
    except Bill.DoesNotExist:
        logger.error(f"未找到对应的Bill: out_trade_no={out_trade_no}")
        return

    if trade_status == 'SUCCESS':
        bill.payment_status = 'completed'
        bill.save()
        logger.info(f"Bill已完成: out_trade_no={out_trade_no}, transaction_id={transaction_id}")
    else:
        bill.payment_status = 'failed'
        bill.save()
        logger.warning(f"支付失败: out_trade_no={out_trade_no}, trade_status={trade_status}")


@csrf_exempt
def wechat_callback(request, callback_type):
    """统一处理支付和退款的回调"""
    if request.method != 'POST':
        return HttpResponse(status=405)

    pay_helper = WeChatPayHelper()
    xml = request.body

    data = pay_helper.parse_callback(xml, callback_type=callback_type)
    if callback_type == 'payment':
        signature = data.get('sign')
        if not signature:
            logger.error("签名缺失")
            return error_response("Missing Signature")

        if not pay_helper.verify_signature(xml, signature):
            logger.error("签名验证失败")
            return error_response("Invalid Signature")

    try:
        if callback_type == 'payment':
            handle_payment_callback(data)
        else:
            logger.error(f"微信支付问题未知的回调类型: {callback_type}")
            return error_response("Unknown Callback Type")

        return HttpResponse('<xml><return_code><![CDATA[SUCCESS]]></return_code></xml>')
    except WeChatPayException as e:
        logger.error(f"WeChatPayException: {e}")
        return error_response("WeChatPay Exception")
    except Exception as e:
        logger.error(f"回调处理失败: {e}")
        return error_response("Internal Error")


class CreatePaymentView(APIView):
    """创建支付订单的API视图"""

    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """创建支付订单"""
        data = request.data
        openid = data.get('open_id')
        total_fee = data.get('total_fee')
        body = data.get('body', '用户支付')

        # 参数验证
        if not all([openid, total_fee]):
            return Response(
                {'error': '缺少必要参数'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            total_fee = int(total_fee)
            if total_fee <= 0:
                raise ValueError("金额必须大于0")
        except (ValueError, TypeError):
            return Response(
                {'error': '金额格式不正确'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 验证openid
        if openid != request.user.openid:
            return Response(
                {'error': 'openid不匹配'},
                status=status.HTTP_400_BAD_REQUEST
            )

        logger.info(f"用户开始创建支付订单: 用户ID={request.user.id}, openid={openid}, 金额={total_fee}")

        pay_helper = WeChatPayHelper()
        try:
            with transaction.atomic():
                # 生成唯一订单号
                out_trade_no = pay_helper.generate_out_trade_no()

                # 创建支付订单
                order = pay_helper.create_payment_order(
                    openid, total_fee, body, out_trade_no=out_trade_no
                )

                # 创建Bill记录
                bill = Bill.objects.create(
                    out_trade_no=out_trade_no,
                    user=request.user,
                    transaction_type='payment',
                    amount=Decimal(total_fee) / 100,  # 转换为元
                    payment_method='wechat',
                    payment_status='pending',
                    description=body,
                )

                logger.info(f"创建支付订单成功: 用户ID={request.user.id}, 订单号={out_trade_no}")

                response_data = {
                    'order': order,
                    'bill_id': bill.id,
                    'out_trade_no': out_trade_no
                }
                return Response(response_data, status=status.HTTP_200_OK)

        except WeChatPayException as e:
            logger.error(f"WeChatPayException: {e}")
            return Response(
                {'error': '微信支付异常'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(f"创建支付订单失败: {e}")
            return Response(
                {'error': '创建支付订单失败'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )