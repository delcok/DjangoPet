# -*- coding: utf-8 -*-
# @Time    : 2025/11/27
# @Author  : Simplified Payment System

import logging
from datetime import timedelta
from django.db.models import Count

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.core.cache import cache

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from wechatpy.exceptions import WeChatPayException

from bill.models import Bill, ServiceOrder
from bill.serializers import (
    ServiceOrderListSerializer,
    ServiceOrderDetailSerializer,
    ServiceOrderCreateSerializer,
    ServiceOrderUpdateSerializer,
    ServiceOrderCancelSerializer,
)
from bill.filters import ServiceOrderFilter
from bill.pagination import StandardResultsSetPagination
from utils.authentication import UserAuthentication
from utils.permission import IsUserOwner
from utils.wechat_pay import WeChatPayHelper

logger = logging.getLogger(__name__)


# ==================== 服务订单管理 ====================

class ServiceOrderViewSet(viewsets.ModelViewSet):
    """
    服务订单管理（不涉及支付）

    list: 获取订单列表
    create: 创建服务订单
    retrieve: 获取订单详情
    update/partial_update: 修改订单信息
    destroy: 不允许删除订单

    自定义动作：
    - cancel: 取消订单
    """
    permission_classes = [IsUserOwner]
    authentication_classes = [UserAuthentication]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ServiceOrderFilter
    search_fields = ['service_address', 'contact_phone', 'customer_notes']
    ordering_fields = ['created_at', 'scheduled_date', 'total_price', 'status']
    ordering = ['-created_at']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        """获取查询集 - 只返回当前用户的订单"""
        queryset = ServiceOrder.objects.select_related(
            'user', 'staff', 'base_service'
        ).prefetch_related(
            'pets', 'additional_services', 'bills'
        )
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

    def create(self, request, *args, **kwargs):
        """
        创建服务订单
        重写此方法以确保返回包含 id 的完整数据
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # 保存订单
        service_order = serializer.save()

        # 使用详情序列化器返回完整数据（包含 id）
        detail_serializer = ServiceOrderDetailSerializer(
            service_order,
            context={'request': request}
        )

        headers = self.get_success_headers(detail_serializer.data)

        logger.info(
            f"订单创建成功: Order ID={service_order.id}, "
            f"User ID={request.user.id}, "
            f"Amount={service_order.final_price}"
        )

        return Response(
            detail_serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """
        获取订单统计信息

        GET /api/bill/service-orders/statistics/

        返回各状态的订单数量
        """
        try:
            # 获取当前用户的订单
            queryset = self.get_queryset()

            # 统计各状态的订单数量
            status_stats = queryset.values('status').annotate(
                count=Count('id')
            ).order_by('status')

            # 转换为列表格式
            status_distribution = [
                {
                    'status': item['status'],
                    'status_display': dict(ServiceOrder.STATUS_CHOICES).get(item['status'], item['status']),
                    'count': item['count']
                }
                for item in status_stats
            ]

            # 计算总订单数
            total_orders = queryset.count()

            # 统计待支付订单数
            pending_payment = queryset.filter(status='draft').count()

            # 统计待服务订单数（paid, confirmed, assigned）
            pending_service = queryset.filter(
                status__in=['paid', 'confirmed', 'assigned']
            ).count()

            # 统计已完成订单数
            completed_orders = queryset.filter(status='completed').count()

            logger.info(
                f"获取订单统计: User ID={request.user.id}, "
                f"Total={total_orders}, Pending={pending_payment}"
            )

            return Response({
                'total_orders': total_orders,
                'pending_payment': pending_payment,
                'pending_service': pending_service,
                'completed_orders': completed_orders,
                'status_distribution': status_distribution
            })

        except Exception as e:
            logger.error(f"获取订单统计失败: {e}", exc_info=True)
            return Response(
                {'error': '获取统计信息失败'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

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

        try:
            with transaction.atomic():
                # 取消订单
                serializer.save()

                # 如果有待支付的账单，一并取消
                pending_bills = Bill.objects.filter(
                    service_order=service_order,
                    transaction_type='payment',
                    payment_status='pending'
                )

                for bill in pending_bills:
                    bill.payment_status = 'cancelled'
                    bill.failure_reason = '用户取消订单'
                    bill.save()

                logger.info(f"订单已取消: Order ID={service_order.id}, User ID={request.user.id}")

        except Exception as e:
            logger.error(f"取消订单失败: {e}", exc_info=True)
            return Response(
                {'error': '取消订单失败，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        return Response({
            'message': '订单已取消',
            'order_id': service_order.id,
            'status': service_order.status
        })


# ==================== 支付接口 ====================

class CreatePaymentView(APIView):
    """
    创建支付订单（独立接口）

    支持首次支付和重新支付
    重新支付时会自动取消旧的微信订单
    """
    permission_classes = [IsUserOwner]
    authentication_classes = [UserAuthentication]

    @transaction.atomic  # ⭐ 关键修复：添加事务装饰器
    def post(self, request):
        """
        创建支付订单

        POST /api/bill/wechatpay/create_payment/
        {
            "service_order_id": 123,
            "payment_method": "wechat"  // 默认wechat
        }
        """
        service_order_id = request.data.get('service_order_id')
        payment_method = request.data.get('payment_method', 'wechat')

        # 1. 验证参数
        if not service_order_id:
            logger.warning(f"创建支付失败: 缺少订单ID, User ID={request.user.id}")
            return Response(
                {'error': '缺少订单ID'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. 获取订单（现在可以安全使用 select_for_update）
        try:
            service_order = ServiceOrder.objects.select_for_update().get(
                id=service_order_id,
                user=request.user
            )
        except ServiceOrder.DoesNotExist:
            logger.warning(
                f"创建支付失败: 订单不存在, "
                f"Order ID={service_order_id}, User ID={request.user.id}"
            )
            return Response(
                {'error': '订单不存在'},
                status=status.HTTP_404_NOT_FOUND
            )

        # 3. 验证订单状态
        if service_order.status not in ['draft', 'paid']:
            logger.warning(
                f"创建支付失败: 订单状态错误, "
                f"Order ID={service_order.id}, Status={service_order.status}"
            )
            return Response(
                {'error': f'订单状态为 {service_order.get_status_display()}，无法支付'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 4. 如果订单已支付，不允许重复支付
        if service_order.status == 'paid':
            logger.warning(
                f"创建支付失败: 订单已支付, Order ID={service_order.id}"
            )
            return Response(
                {'error': '订单已支付，无需重复支付'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 5. 查找旧的待支付账单
            old_bills = Bill.objects.select_for_update().filter(
                service_order=service_order,
                transaction_type='payment',
                payment_status='pending'
            )

            # 6. 取消旧的微信订单和本地账单
            pay_helper = WeChatPayHelper()
            for old_bill in old_bills:
                if old_bill.payment_method == 'wechat':
                    try:
                        # 尝试取消微信端订单
                        pay_helper.cancel_payment_order(old_bill.out_trade_no)
                        logger.info(f"旧微信订单已取消: {old_bill.out_trade_no}")
                    except WeChatPayException as e:
                        # 订单可能已超时或不存在，忽略错误继续处理
                        logger.warning(
                            f"取消微信订单失败（可能已超时，继续处理）: "
                            f"out_trade_no={old_bill.out_trade_no}, error={e}"
                        )

                # 更新本地账单状态
                old_bill.payment_status = 'cancelled'
                old_bill.failure_reason = '用户重新发起支付'
                old_bill.save()
                logger.info(f"旧账单已取消: Bill ID={old_bill.id}")

            # 7. 创建新的支付账单
            bill = Bill.objects.create(
                user=request.user,
                service_order=service_order,
                transaction_type='payment',
                amount=service_order.final_price,
                payment_method=payment_method,
                payment_status='pending',
                description=f'服务订单#{service_order.id}支付',
                expired_at=timezone.now() + timedelta(minutes=30)
            )

            # 8. 调用微信支付
            if payment_method == 'wechat':
                try:
                    # 获取用户的 openid（兼容不同的属性名）
                    openid = getattr(request.user, 'openid', None) or getattr(request.user, 'wechat_openid', None)

                    if not openid:
                        logger.error(f"用户未绑定微信: User ID={request.user.id}")
                        bill.payment_status = 'failed'
                        bill.failure_reason = '用户未绑定微信'
                        bill.save()
                        return Response(
                            {'error': '您还未绑定微信，请先绑定后再支付'},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    # 转换金额为分（微信支付要求）
                    total_fee = int(service_order.final_price * 100)
                    if total_fee <= 0:
                        raise ValueError('支付金额必须大于0')

                    body = f'服务订单#{service_order.id}'

                    # 调用微信支付API
                    payment_params = pay_helper.create_payment_order(
                        openid=openid,
                        total_fee=total_fee,
                        body=body,
                        out_trade_no=bill.out_trade_no
                    )

                    logger.info(
                        f"✅ 支付订单创建成功: "
                        f"User ID={request.user.id}, "
                        f"Order ID={service_order.id}, "
                        f"Bill ID={bill.id}, "
                        f"out_trade_no={bill.out_trade_no}, "
                        f"amount=¥{service_order.final_price}"
                    )

                    # 9. 返回支付参数
                    return Response({
                        'bill_id': bill.id,
                        'out_trade_no': bill.out_trade_no,
                        'amount': str(bill.amount),
                        'expired_at': bill.expired_at,
                        'payment_method': bill.payment_method,
                        'payment_params': payment_params,  # 前端调起支付需要的参数
                    }, status=status.HTTP_200_OK)

                except ValueError as e:
                    logger.error(f"参数错误: {e}, Bill ID={bill.id}")
                    bill.payment_status = 'failed'
                    bill.failure_reason = str(e)
                    bill.save()
                    return Response(
                        {'error': str(e)},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                except WeChatPayException as e:
                    logger.error(
                        f"微信支付异常: {e}, "
                        f"Bill ID={bill.id}, "
                        f"out_trade_no={bill.out_trade_no}",
                        exc_info=True
                    )
                    bill.payment_status = 'failed'
                    bill.failure_reason = f'微信支付服务异常: {str(e)}'
                    bill.save()
                    return Response(
                        {'error': '微信支付服务异常，请稍后重试'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
                except Exception as e:
                    logger.error(
                        f"创建微信支付订单失败: {e}, Bill ID={bill.id}",
                        exc_info=True
                    )
                    bill.payment_status = 'failed'
                    bill.failure_reason = f'创建支付订单失败: {str(e)}'
                    bill.save()
                    return Response(
                        {'error': '创建支付订单失败，请稍后重试'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            else:
                # 其他支付方式
                logger.warning(f"不支持的支付方式: {payment_method}")
                return Response({
                    'bill_id': bill.id,
                    'out_trade_no': bill.out_trade_no,
                    'amount': str(bill.amount),
                    'payment_method': bill.payment_method,
                    'message': '暂不支持该支付方式'
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(
                f"创建支付订单失败: {e}, "
                f"Order ID={service_order_id}, "
                f"User ID={request.user.id}",
                exc_info=True
            )
            return Response(
                {'error': '创建支付订单失败，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class QueryPaymentView(APIView):
    """
    查询支付状态（前端轮询用）

    GET /api/bill/payment/query/?out_trade_no=xxx
    """
    permission_classes = [IsUserOwner]
    authentication_classes = [UserAuthentication]

    def get(self, request):
        """查询支付状态"""
        out_trade_no = request.query_params.get('out_trade_no')

        if not out_trade_no:
            return Response(
                {'error': '缺少订单号'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            bill = Bill.objects.select_related('service_order').get(
                out_trade_no=out_trade_no,
                user=request.user
            )

            response_data = {
                'out_trade_no': bill.out_trade_no,
                'payment_status': bill.payment_status,
                'payment_status_display': bill.get_payment_status_display(),
                'paid_at': bill.paid_at,
                'amount': str(bill.amount),
            }

            # 添加服务订单信息（如果存在）
            if bill.service_order:
                response_data['service_order'] = {
                    'id': bill.service_order.id,
                    'status': bill.service_order.status,
                    'status_display': bill.service_order.get_status_display(),
                }

            return Response(response_data)

        except Bill.DoesNotExist:
            logger.warning(
                f"查询支付状态失败: 账单不存在, "
                f"out_trade_no={out_trade_no}, User ID={request.user.id}"
            )
            return Response(
                {'error': '账单不存在'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"查询支付状态失败: {e}", exc_info=True)
            return Response(
                {'error': '查询失败，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ==================== 微信支付回调 ====================

def success_response():
    """成功响应"""
    return HttpResponse(
        '<xml><return_code><![CDATA[SUCCESS]]></return_code>'
        '<return_msg><![CDATA[OK]]></return_msg></xml>',
        content_type='text/xml'
    )


def error_response(message):
    """错误响应"""
    return HttpResponse(
        f'<xml><return_code><![CDATA[FAIL]]></return_code>'
        f'<return_msg><![CDATA[{message}]]></return_msg></xml>',
        content_type='text/xml'
    )


@csrf_exempt
def wechat_callback(request, callback_type):
    """
    微信支付回调

    POST /api/bill/wechat_callback/payment/

    只处理支付回调，更新订单和账单状态
    """
    if request.method != 'POST':
        return HttpResponse(status=405)

    if callback_type != 'payment':
        logger.error(f"不支持的回调类型: {callback_type}")
        return error_response("不支持的回调类型")

    try:
        pay_helper = WeChatPayHelper()
        xml_data = request.body

        # 1. 解析回调数据
        data = pay_helper.parse_callback(xml_data, callback_type='payment')

        # 2. 验证签名
        signature = data.get('sign')
        if not signature:
            logger.error("支付回调缺少签名")
            return error_response("Missing Signature")

        if not pay_helper.verify_signature(xml_data, signature):
            logger.error("支付回调签名验证失败")
            return error_response("Invalid Signature")

        # 3. 处理支付回调
        out_trade_no = data.get('out_trade_no')
        transaction_id = data.get('transaction_id')
        result_code = data.get('result_code')

        logger.info(
            f"📱 收到支付回调: "
            f"out_trade_no={out_trade_no}, "
            f"transaction_id={transaction_id}, "
            f"result_code={result_code}"
        )

        # 4. 查找账单
        try:
            bill = Bill.objects.select_related('service_order').get(
                out_trade_no=out_trade_no,
                transaction_type='payment'
            )
        except Bill.DoesNotExist:
            logger.error(f"账单不存在: out_trade_no={out_trade_no}")
            return error_response("Bill Not Found")

        # 5. 防止重复处理
        if bill.payment_status in ['success', 'failed', 'cancelled']:
            logger.info(
                f"账单已处理，跳过: "
                f"Bill ID={bill.id}, status={bill.payment_status}"
            )
            return success_response()

        # 6. 更新账单和订单状态
        try:
            with transaction.atomic():
                if result_code == 'SUCCESS':
                    # 支付成功
                    bill.payment_status = 'success'
                    bill.third_party_no = transaction_id
                    bill.paid_at = timezone.now()
                    bill.save()

                    # 更新服务订单状态
                    if bill.service_order:
                        service_order = bill.service_order
                        service_order.status = 'paid'
                        service_order.paid_at = bill.paid_at
                        service_order.save()

                        logger.info(
                            f"✅ 支付成功: "
                            f"Bill ID={bill.id}, "
                            f"Order ID={service_order.id}, "
                            f"transaction_id={transaction_id}, "
                            f"amount=¥{bill.amount}"
                        )

                        # 清理缓存
                        cache_key = f"user_orders:{bill.user.id}"
                        cache.delete(cache_key)
                else:
                    # 支付失败
                    bill.payment_status = 'failed'
                    bill.failure_reason = data.get('err_code_des', '支付失败')
                    bill.save()

                    logger.warning(
                        f"❌ 支付失败: "
                        f"Bill ID={bill.id}, "
                        f"原因={bill.failure_reason}"
                    )

        except Exception as e:
            logger.error(f"处理支付回调失败: {e}", exc_info=True)
            return error_response("Internal Error")

        return success_response()

    except WeChatPayException as e:
        logger.error(f"微信支付回调异常: {e}", exc_info=True)
        return error_response("WeChatPay Exception")
    except Exception as e:
        logger.error(f"回调处理失败: {e}", exc_info=True)
        return error_response("Internal Error")