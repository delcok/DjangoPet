# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Modified for better order flow

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Count
from django.utils import timezone

from bill.models import Bill, ServiceOrder
from bill.serializers import (
    # 服务订单序列化器
    ServiceOrderListSerializer,
    ServiceOrderDetailSerializer,
    ServiceOrderCreateSerializer,
    ServiceOrderUpdateSerializer,
    ServiceOrderCancelSerializer,
    # 账单序列化器
    BillListSerializer,
    BillDetailSerializer,
    CreatePaymentBillSerializer,
    RefundBillSerializer,
)
from bill.filters import ServiceOrderFilter, BillFilter
from bill.pagination import StandardResultsSetPagination


class ServiceOrderViewSet(viewsets.ModelViewSet):
    """
    服务订单视图集

    list: 获取订单列表
    create: 创建服务订单（选择服务后创建）
    retrieve: 获取订单详情
    update/partial_update: 修改订单信息（仅限待支付/已支付状态）
    destroy: 不允许删除订单

    自定义动作：
    - cancel: 取消订单
    - create_payment: 创建支付账单
    - statistics: 获取订单统计信息
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ServiceOrderFilter
    search_fields = ['service_address', 'contact_phone', 'customer_notes']
    ordering_fields = ['created_at', 'scheduled_date', 'total_price', 'status']
    ordering = ['-created_at']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        """获取查询集"""
        queryset = ServiceOrder.objects.select_related(
            'user', 'staff', 'base_service'
        ).prefetch_related(
            'pets', 'additional_services', 'bills'
        )

        # 普通用户只能看到自己的订单
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)

        return queryset

    def get_serializer_class(self):
        """根据操作返回不同的序列化器"""
        if self.action == 'list':
            return ServiceOrderListSerializer
        elif self.action == 'create':
            return ServiceOrderCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ServiceOrderUpdateSerializer
        elif self.action == 'cancel':
            return ServiceOrderCancelSerializer
        return ServiceOrderDetailSerializer

    def perform_destroy(self, instance):
        """禁止删除订单"""
        raise ValidationError("订单不允许删除")

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """
        取消订单
        POST /api/bill/service-orders/{id}/cancel/
        {
            "cancel_reason": "取消原因"
        }
        """
        service_order = self.get_object()
        serializer = ServiceOrderCancelSerializer(
            service_order,
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'message': '订单已取消',
            'order_id': service_order.id,
            'status': service_order.status
        })

    @action(detail=True, methods=['post'])
    def create_payment(self, request, pk=None):
        """
        为服务订单创建支付账单
        POST /api/bill/service-orders/{id}/create_payment/
        {
            "payment_method": "wechat"  // wechat/alipay/balance/cash
        }
        """
        service_order = self.get_object()

        # 构建请求数据
        data = {
            'service_order_id': service_order.id,
            'payment_method': request.data.get('payment_method', 'wechat')
        }

        serializer = CreatePaymentBillSerializer(
            data=data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        bill = serializer.save()

        # 返回创建的账单信息
        return Response({
            'message': '支付订单创建成功',
            'bill': BillDetailSerializer(bill).data,
            'payment_info': {
                'out_trade_no': bill.out_trade_no,
                'amount': str(bill.amount),
                'payment_method': bill.payment_method,
                # 这里可以添加调用第三方支付接口的逻辑
                # 'payment_url': '...',  # 支付链接
                # 'qr_code': '...',      # 二维码
            }
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        获取订单统计信息
        GET /api/bill/service-orders/statistics/
        """
        queryset = self.get_queryset()

        # 基础统计
        total_count = queryset.count()
        total_amount = queryset.filter(
            status__in=['paid', 'confirmed', 'assigned', 'in_progress', 'completed']
        ).aggregate(total=Sum('final_price'))['total'] or 0

        # 状态分布
        status_distribution = queryset.values('status').annotate(
            count=Count('id'),
            amount=Sum('final_price')
        ).order_by('status')

        # 今日统计
        today = timezone.now().date()
        today_orders = queryset.filter(created_at__date=today)
        today_count = today_orders.count()
        today_amount = today_orders.filter(
            status__in=['paid', 'confirmed', 'assigned', 'in_progress', 'completed']
        ).aggregate(total=Sum('final_price'))['total'] or 0

        # 本月统计
        current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_orders = queryset.filter(created_at__gte=current_month)
        month_count = month_orders.count()
        month_amount = month_orders.filter(
            status__in=['paid', 'confirmed', 'assigned', 'in_progress', 'completed']
        ).aggregate(total=Sum('final_price'))['total'] or 0

        return Response({
            'total': {
                'count': total_count,
                'amount': str(total_amount)
            },
            'today': {
                'count': today_count,
                'amount': str(today_amount)
            },
            'month': {
                'count': month_count,
                'amount': str(month_amount)
            },
            'status_distribution': [{
                'status': item['status'],
                'status_display': dict(ServiceOrder.STATUS_CHOICES).get(item['status']),
                'count': item['count'],
                'amount': str(item['amount'] or 0)
            } for item in status_distribution]
        })


class BillViewSet(viewsets.ModelViewSet):
    """
    账单/支付订单视图集

    list: 获取账单列表
    retrieve: 获取账单详情
    create: 不允许直接创建账单（通过服务订单创建）
    update/destroy: 不允许修改或删除账单

    自定义动作：
    - create_payment: 为服务订单创建支付账单
    - create_refund: 创建退款账单
    - check_status: 检查支付状态
    - statistics: 获取账单统计信息
    """
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = BillFilter
    search_fields = ['out_trade_no', 'third_party_no', 'description']
    ordering_fields = ['created_at', 'amount', 'payment_status']
    ordering = ['-created_at']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        """获取查询集"""
        queryset = Bill.objects.select_related(
            'user', 'service_order', 'original_bill'
        )

        # 普通用户只能看到自己的账单
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)

        return queryset

    def get_serializer_class(self):
        """根据操作返回不同的序列化器"""
        if self.action == 'list':
            return BillListSerializer
        return BillDetailSerializer

    def create(self, request, *args, **kwargs):
        """禁止直接创建账单"""
        return Response(
            {'error': '请通过服务订单创建支付账单'},
            status=status.HTTP_400_BAD_REQUEST
        )

    def update(self, request, *args, **kwargs):
        """禁止修改账单"""
        return Response(
            {'error': '账单不允许修改'},
            status=status.HTTP_400_BAD_REQUEST
        )

    def destroy(self, request, *args, **kwargs):
        """禁止删除账单"""
        return Response(
            {'error': '账单不允许删除'},
            status=status.HTTP_400_BAD_REQUEST
        )

    @action(detail=False, methods=['post'])
    def create_payment(self, request):
        """
        为服务订单创建支付账单
        POST /api/bill/bills/create_payment/
        {
            "service_order_id": 1,
            "payment_method": "wechat"
        }
        """
        serializer = CreatePaymentBillSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        bill = serializer.save()

        return Response({
            'message': '支付账单创建成功',
            'bill': BillDetailSerializer(bill).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def create_refund(self, request):
        """
        创建退款账单
        POST /api/bill/bills/create_refund/
        {
            "service_order_id": 1,
            "refund_amount": 100.00,  // 可选，不填则全额退款
            "refund_reason": "退款原因"
        }
        """
        serializer = RefundBillSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        refund_bill = serializer.save()

        return Response({
            'message': '退款申请已创建',
            'bill': BillDetailSerializer(refund_bill).data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def check_status(self, request, pk=None):
        """
        检查支付状态
        GET /api/bill/bills/{id}/check_status/

        这里可以调用第三方支付接口查询实际支付状态
        """
        bill = self.get_object()

        # TODO: 调用第三方支付接口查询实际状态
        # 示例逻辑：
        # if bill.payment_method == 'wechat':
        #     status = check_wechat_payment_status(bill.out_trade_no)
        #     if status == 'SUCCESS':
        #         bill.mark_as_paid(third_party_no='...')

        return Response({
            'out_trade_no': bill.out_trade_no,
            'payment_status': bill.payment_status,
            'payment_status_display': bill.get_payment_status_display(),
            'amount': str(bill.amount),
            'paid_at': bill.paid_at
        })

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        获取账单统计信息
        GET /api/bill/bills/statistics/
        """
        queryset = self.get_queryset()

        # 总体统计
        total_stats = queryset.aggregate(
            total_count=Count('id'),
            total_amount=Sum('amount')
        )

        # 按交易类型统计
        type_stats = queryset.values('transaction_type').annotate(
            count=Count('id'),
            amount=Sum('amount')
        ).order_by('transaction_type')

        # 按支付方式统计
        method_stats = queryset.filter(
            transaction_type='payment',
            payment_status='success'
        ).values('payment_method').annotate(
            count=Count('id'),
            amount=Sum('amount')
        ).order_by('payment_method')

        # 今日收入
        today = timezone.now().date()
        today_income = queryset.filter(
            transaction_type='payment',
            payment_status='success',
            paid_at__date=today
        ).aggregate(total=Sum('amount'))['total'] or 0

        # 本月收入
        current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_income = queryset.filter(
            transaction_type='payment',
            payment_status='success',
            paid_at__gte=current_month
        ).aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            'total': {
                'count': total_stats['total_count'] or 0,
                'amount': str(total_stats['total_amount'] or 0)
            },
            'today_income': str(today_income),
            'month_income': str(month_income),
            'by_type': [{
                'type': item['transaction_type'],
                'type_display': dict(Bill.TRANSACTION_TYPE_CHOICES).get(item['transaction_type']),
                'count': item['count'],
                'amount': str(item['amount'] or 0)
            } for item in type_stats],
            'by_payment_method': [{
                'method': item['payment_method'],
                'method_display': dict(Bill.PAYMENT_CHOICES).get(item['payment_method']),
                'count': item['count'],
                'amount': str(item['amount'] or 0)
            } for item in method_stats]
        })


@api_view(['POST'])
@permission_classes([AllowAny])  # 支付回调通常不需要认证
def wechat_callback(request, callback_type):
    """
    微信支付回调
    POST /api/bill/wechat_callback/payment/  支付回调
    POST /api/bill/wechat_callback/refund/   退款回调
    """
    # TODO: 验证微信签名
    # TODO: 解析微信回调数据

    if callback_type == 'payment':
        # 处理支付回调
        out_trade_no = request.data.get('out_trade_no')
        transaction_id = request.data.get('transaction_id')
        result_code = request.data.get('result_code')

        try:
            bill = Bill.objects.get(out_trade_no=out_trade_no)

            if result_code == 'SUCCESS' and bill.payment_status == 'pending':
                # 标记为已支付
                bill.mark_as_paid(third_party_no=transaction_id)

                return Response({
                    'code': 'SUCCESS',
                    'message': '成功'
                })

        except Bill.DoesNotExist:
            return Response({
                'code': 'FAIL',
                'message': '订单不存在'
            }, status=status.HTTP_400_BAD_REQUEST)

    elif callback_type == 'refund':
        # 处理退款回调
        out_refund_no = request.data.get('out_refund_no')
        refund_status = request.data.get('refund_status')

        try:
            refund_bill = Bill.objects.get(
                out_trade_no=out_refund_no,
                transaction_type='refund'
            )

            if refund_status == 'SUCCESS':
                refund_bill.payment_status = 'refunded'
                refund_bill.save()

                # 更新服务订单状态
                if refund_bill.service_order:
                    refund_bill.service_order.status = 'refunded'
                    refund_bill.service_order.save()

                return Response({
                    'code': 'SUCCESS',
                    'message': '成功'
                })

        except Bill.DoesNotExist:
            return Response({
                'code': 'FAIL',
                'message': '退款订单不存在'
            }, status=status.HTTP_400_BAD_REQUEST)

    return Response({
        'code': 'FAIL',
        'message': '未知的回调类型'
    }, status=status.HTTP_400_BAD_REQUEST)


class CreatePaymentView(APIView):
    """
    统一的支付创建接口
    用于处理各种支付场景
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        创建支付
        POST /api/bill/wechatpay/create_payment/
        {
            "payment_type": "service_order",  // 支付类型
            "service_order_id": 1,            // 服务订单ID
            "payment_method": "wechat"        // 支付方式
        }
        """
        payment_type = request.data.get('payment_type')

        if payment_type == 'service_order':
            # 服务订单支付
            serializer = CreatePaymentBillSerializer(
                data={
                    'service_order_id': request.data.get('service_order_id'),
                    'payment_method': request.data.get('payment_method', 'wechat')
                },
                context={'request': request}
            )
            serializer.is_valid(raise_exception=True)
            bill = serializer.save()

            # TODO: 调用第三方支付接口
            # payment_result = create_wechat_payment(bill)

            return Response({
                'success': True,
                'message': '支付订单创建成功',
                'data': {
                    'out_trade_no': bill.out_trade_no,
                    'amount': str(bill.amount),
                    'payment_method': bill.payment_method,
                    # 'payment_url': payment_result.get('payment_url'),
                    # 'qr_code': payment_result.get('qr_code'),
                }
            }, status=status.HTTP_201_CREATED)

        elif payment_type == 'recharge':
            # 余额充值
            # TODO: 实现充值逻辑
            pass

        else:
            return Response({
                'success': False,
                'message': '不支持的支付类型'
            }, status=status.HTTP_400_BAD_REQUEST)