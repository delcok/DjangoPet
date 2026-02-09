# -*- coding: utf-8 -*-
# Mall Views - 增加微信支付集成

import logging

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.core.cache import cache

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response

from wechatpy.exceptions import WeChatPayException

from utils.authentication import UserAuthentication, AdminAuthentication
from utils.permission import IsUserOwner, IsOwnerOrAdmin, AnyUser
from .filters import ProductFilter, OrderFilter
from .models import (
    Category, Product, ProductImage, ProductVideo,
    SpecificationName, SKU,
    Order, OrderItem, OrderLog, CartItem, ProductFavorite,
    PRODUCT_STATUS_ON_SALE,
    ORDER_STATUS_PENDING_PAYMENT, ORDER_STATUS_PENDING_SHIPMENT,
    ORDER_STATUS_SHIPPED, ORDER_STATUS_COMPLETED, ORDER_STATUS_REFUNDING,
    ORDER_STATUS_CANCELLED, ORDER_STATUS_REFUNDED,
    PAYMENT_METHOD_WECHAT,
)
from .serializers import (
    CategorySerializer, CategoryAdminSerializer,
    ProductListSerializer, ProductDetailSerializer, ProductAdminSerializer,
    SKUSerializer, SKUAdminSerializer,
    SpecificationNameSerializer,
    CartItemSerializer, CartItemCreateSerializer,
    OrderListSerializer, OrderDetailSerializer, OrderCreateSerializer,
    OrderPaySerializer, OrderShipSerializer,
    ProductFavoriteSerializer
)
from .pagination import StandardResultsSetPagination, SmallResultsSetPagination
from utils.wechat_pay import WeChatPayHelper

logger = logging.getLogger(__name__)


# ==================== 分类视图 ====================

class CategoryViewSet(viewsets.ModelViewSet):
    """商品分类视图集"""
    queryset = Category.objects.all()
    permission_classes = [AnyUser]
    filterset_fields = ['parent', 'is_active']
    search_fields = ['name']
    ordering_fields = ['sort_order', 'created_at']

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return CategoryAdminSerializer
        return CategorySerializer

    def get_authenticators(self):
        # GET/HEAD/OPTIONS 为公开接口无需认证，写操作需要管理员认证
        if self.request and self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return []
        return [AdminAuthentication()]

    def get_queryset(self):
        if self.action == 'tree':
            return Category.objects.filter(parent__isnull=True, is_active=True)
        return super().get_queryset()

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """获取分类树"""
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


# ==================== 商品视图 ====================

class ProductViewSet(viewsets.ModelViewSet):
    """商品视图集"""
    queryset = Product.objects.all()
    permission_classes = [AnyUser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ['name', 'subtitle', 'description', 'brand']
    ordering_fields = ['price', 'sales', 'created_at', 'sort_order']
    ordering = ['-sort_order', '-created_at']
    pagination_class = StandardResultsSetPagination

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        if self.action == 'retrieve':
            return ProductDetailSerializer
        return ProductAdminSerializer

    def get_authenticators(self):
        # GET/HEAD/OPTIONS 为公开接口无需认证，写操作需要管理员认证
        if self.request and self.request.method in ('GET', 'HEAD', 'OPTIONS'):
            return []
        return [AdminAuthentication()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if not self.request.user.is_staff:
            queryset = queryset.filter(status=PRODUCT_STATUS_ON_SALE)
        return queryset

    @action(detail=False, methods=['get'])
    def recommended(self, request):
        queryset = self.get_queryset().filter(
            is_recommended=True, status=PRODUCT_STATUS_ON_SALE
        )[:10]
        serializer = ProductListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def hot(self, request):
        queryset = self.get_queryset().filter(
            is_hot=True, status=PRODUCT_STATUS_ON_SALE
        )[:10]
        serializer = ProductListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def new(self, request):
        queryset = self.get_queryset().filter(
            is_new=True, status=PRODUCT_STATUS_ON_SALE
        )[:10]
        serializer = ProductListSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        product = self.get_object()
        new_status = request.data.get('status')
        if new_status is None:
            return Response({'error': '请提供商品状态'}, status=status.HTTP_400_BAD_REQUEST)
        product.status = new_status
        product.save()
        return Response({'status': 'success'})

    @action(detail=True, methods=['post'])
    def update_images(self, request, pk=None):
        product = self.get_object()
        images_data = request.data.get('images', [])
        product.images.all().delete()
        for idx, image_data in enumerate(images_data):
            ProductImage.objects.create(
                product=product,
                image_url=image_data.get('image_url'),
                is_main=image_data.get('is_main', False),
                sort_order=idx
            )
        return Response({'status': 'success'})

    @action(detail=True, methods=['post'])
    def update_videos(self, request, pk=None):
        product = self.get_object()
        videos_data = request.data.get('videos', [])
        product.videos.all().delete()
        for idx, video_data in enumerate(videos_data):
            ProductVideo.objects.create(
                product=product,
                video_url=video_data.get('video_url'),
                cover_url=video_data.get('cover_url', ''),
                title=video_data.get('title', ''),
                duration=video_data.get('duration'),
                sort_order=idx
            )
        return Response({'status': 'success'})


# ==================== SKU视图 ====================

class SKUViewSet(viewsets.ModelViewSet):
    queryset = SKU.objects.all()
    permission_classes = [AnyUser]
    authentication_classes = [AdminAuthentication]
    filterset_fields = ['product', 'is_active']

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return SKUSerializer
        return SKUAdminSerializer

    @action(detail=False, methods=['get'])
    def by_product(self, request):
        product_id = request.query_params.get('product_id')
        if not product_id:
            return Response({'error': '请提供商品ID'}, status=status.HTTP_400_BAD_REQUEST)
        queryset = self.get_queryset().filter(product_id=product_id, is_active=True)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


# ==================== 规格视图 ====================

class SpecificationViewSet(viewsets.ModelViewSet):
    queryset = SpecificationName.objects.all()
    serializer_class = SpecificationNameSerializer
    permission_classes = [AnyUser]
    authentication_classes = [AdminAuthentication]


# ==================== 购物车视图 ====================

class CartViewSet(viewsets.ModelViewSet):
    permission_classes = [IsUserOwner]
    authentication_classes = [UserAuthentication]

    def get_queryset(self):
        return CartItem.objects.filter(user=self.request.user).select_related('product', 'sku')

    def get_serializer_class(self):
        if self.action == 'create':
            return CartItemCreateSerializer
        return CartItemSerializer

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=False, methods=['get'])
    def count(self, request):
        count = self.get_queryset().count()
        total_quantity = sum(item.quantity for item in self.get_queryset())
        return Response({'count': count, 'total_quantity': total_quantity})

    @action(detail=False, methods=['post'])
    def update_quantity(self, request):
        cart_item_id = request.data.get('cart_item_id')
        quantity = request.data.get('quantity', 1)
        try:
            cart_item = self.get_queryset().get(id=cart_item_id)
        except CartItem.DoesNotExist:
            return Response({'error': '购物车项不存在'}, status=status.HTTP_404_NOT_FOUND)
        stock = cart_item.sku.stock if cart_item.sku else cart_item.product.stock
        if quantity > stock:
            return Response({'error': f'库存不足，当前库存：{stock}'}, status=status.HTTP_400_BAD_REQUEST)
        cart_item.quantity = quantity
        cart_item.save()
        serializer = CartItemSerializer(cart_item)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def select(self, request):
        cart_item_ids = request.data.get('cart_item_ids', [])
        is_selected = request.data.get('is_selected', True)
        self.get_queryset().filter(id__in=cart_item_ids).update(is_selected=is_selected)
        return Response({'status': 'success'})

    @action(detail=False, methods=['post'])
    def select_all(self, request):
        is_selected = request.data.get('is_selected', True)
        self.get_queryset().update(is_selected=is_selected)
        return Response({'status': 'success'})

    @action(detail=False, methods=['post'])
    def clear(self, request):
        self.get_queryset().delete()
        return Response({'status': 'success'})

    @action(detail=False, methods=['delete'])
    def batch_delete(self, request):
        cart_item_ids = request.data.get('cart_item_ids', [])
        self.get_queryset().filter(id__in=cart_item_ids).delete()
        return Response({'status': 'success'})


# ==================== 订单视图 ====================

class OrderViewSet(viewsets.ModelViewSet):
    """订单视图集 - 集成微信支付"""
    permission_classes = [IsUserOwner]
    authentication_classes = [UserAuthentication]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = OrderFilter
    ordering_fields = ['created_at', 'pay_amount']
    ordering = ['-created_at']
    pagination_class = SmallResultsSetPagination

    def get_queryset(self):
        user = self.request.user
        return Order.objects.filter(user=user).prefetch_related('items')

    def get_serializer_class(self):
        if self.action == 'list':
            return OrderListSerializer
        if self.action == 'retrieve':
            return OrderDetailSerializer
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        return Response(
            OrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        """
        支付订单 - 集成微信支付

        POST /api/mall/orders/{id}/pay/
        {
            "payment_method": 1  // 1=微信支付
        }

        返回微信支付参数，前端调起支付
        """
        order = self.get_object()

        if order.status != ORDER_STATUS_PENDING_PAYMENT:
            return Response(
                {'error': '订单状态不正确，无法支付'},
                status=status.HTTP_400_BAD_REQUEST
            )

        payment_method = request.data.get('payment_method', PAYMENT_METHOD_WECHAT)

        # ====== 微信支付流程 ======
        if payment_method == PAYMENT_METHOD_WECHAT:
            try:
                return self._create_wechat_payment(request, order)
            except Exception as e:
                logger.error(
                    f"商城订单微信支付失败: Order={order.order_no}, error={e}",
                    exc_info=True
                )
                return Response(
                    {'error': '创建支付订单失败，请稍后重试'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            # 非微信支付方式（保留原逻辑，可扩展支付宝等）
            serializer = OrderPaySerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            order.status = ORDER_STATUS_PENDING_SHIPMENT
            order.payment_method = serializer.validated_data['payment_method']
            order.payment_no = serializer.validated_data.get('payment_no', '')
            order.payment_time = timezone.now()
            order.save()

            OrderLog.objects.create(
                order=order,
                action='PAY',
                description=f'订单支付成功，支付方式：{order.get_payment_method_display()}',
                operator=request.user
            )
            return Response(OrderDetailSerializer(order).data)

    def _create_wechat_payment(self, request, order):
        """
        创建微信支付订单（内部方法）

        参考服务订单支付逻辑（CreatePaymentView），适配商城订单模型
        """
        pay_helper = WeChatPayHelper()

        # 1. 获取用户 openid
        openid = getattr(request.user, 'openid', None) or getattr(request.user, 'wechat_openid', None)
        if not openid:
            logger.error(f"用户未绑定微信: User ID={request.user.id}")
            return Response(
                {'error': '您还未绑定微信，请先绑定后再支付'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. 转换金额为分（微信支付要求整数，单位：分）
        total_fee = int(order.pay_amount * 100)
        if total_fee <= 0:
            return Response(
                {'error': '支付金额必须大于0'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. 生成商户订单号（如果订单已有未过期的支付单号，先关闭旧订单）
        #    使用 order_no 加前缀作为 out_trade_no，支持重新支付
        out_trade_no = self._get_or_create_trade_no(order, pay_helper)

        # 4. 调用微信支付API
        body = f'商城订单#{order.order_no}'

        try:
            payment_params = pay_helper.create_payment_order(
                openid=openid,
                total_fee=total_fee,
                body=body,
                out_trade_no=out_trade_no,
                notify_url="https://pet.yimengzhiyuan.com:8080/api/v1/mall/wechat_callback/payment/"

            )
        except WeChatPayException as e:
            logger.error(
                f"微信支付API异常: Order={order.order_no}, error={e}",
                exc_info=True
            )
            return Response(
                {'error': '微信支付服务异常，请稍后重试'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # 5. 保存支付信息到订单
        order.payment_method = PAYMENT_METHOD_WECHAT
        order.payment_no = out_trade_no  # 暂存商户订单号，回调时更新为微信交易号
        order.save()

        # 6. 记录日志
        OrderLog.objects.create(
            order=order,
            action='PAY_CREATE',
            description=f'创建微信支付订单，out_trade_no={out_trade_no}，金额=¥{order.pay_amount}',
            operator=request.user
        )

        logger.info(
            f"✅ 商城支付订单创建成功: "
            f"User={request.user.id}, Order={order.order_no}, "
            f"out_trade_no={out_trade_no}, amount=¥{order.pay_amount}"
        )

        # 7. 返回支付参数给前端
        return Response({
            'order_id': order.id,
            'order_no': order.order_no,
            'out_trade_no': out_trade_no,
            'amount': str(order.pay_amount),
            'payment_params': payment_params,  # 前端调起微信支付需要的参数
        }, status=status.HTTP_200_OK)

    def _get_or_create_trade_no(self, order, pay_helper):
        """
        获取或创建商户订单号

        如果订单之前有过支付尝试（payment_no 不为空），
        先尝试关闭旧的微信订单，再生成新的 trade_no。
        """
        # 如果之前有支付记录，尝试关闭旧订单
        if order.payment_no:
            try:
                pay_helper.cancel_payment_order(order.payment_no)
                logger.info(f"旧微信订单已关闭: {order.payment_no}")
            except WeChatPayException as e:
                # 订单可能已过期或不存在，忽略错误继续
                logger.warning(
                    f"关闭旧微信订单失败（可能已过期）: "
                    f"out_trade_no={order.payment_no}, error={e}"
                )

        # 生成新的商户订单号
        out_trade_no = pay_helper.generate_out_trade_no()
        return out_trade_no

    @action(detail=True, methods=['get'])
    def payment_status(self, request, pk=None):
        """
        查询支付状态（前端轮询用）

        GET /api/mall/orders/{id}/payment_status/
        """
        order = self.get_object()

        response_data = {
            'order_id': order.id,
            'order_no': order.order_no,
            'status': order.status,
            'status_display': order.get_status_display(),
            'payment_method': order.payment_method,
            'payment_time': order.payment_time,
            'pay_amount': str(order.pay_amount),
            'is_paid': order.status != ORDER_STATUS_PENDING_PAYMENT,
        }

        return Response(response_data)

    @action(detail=True, methods=['post'])
    def ship(self, request, pk=None):
        order = self.get_object()
        if order.status != ORDER_STATUS_PENDING_SHIPMENT:
            return Response({'error': '订单状态不正确'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = OrderShipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order.status = ORDER_STATUS_SHIPPED
        order.shipping_company = serializer.validated_data['shipping_company']
        order.shipping_no = serializer.validated_data['shipping_no']
        order.shipping_time = timezone.now()
        order.save()
        OrderLog.objects.create(
            order=order, action='SHIP',
            description=f'订单已发货，快递公司：{order.shipping_company}，单号：{order.shipping_no}',
            operator=request.user
        )
        return Response(OrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def confirm_receipt(self, request, pk=None):
        order = self.get_object()
        if order.status != ORDER_STATUS_SHIPPED:
            return Response({'error': '订单状态不正确'}, status=status.HTTP_400_BAD_REQUEST)
        order.status = ORDER_STATUS_COMPLETED
        order.complete_time = timezone.now()
        order.save()
        OrderLog.objects.create(
            order=order, action='COMPLETE',
            description='买家确认收货，订单完成', operator=request.user
        )
        return Response(OrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        order = self.get_object()
        if order.status not in [ORDER_STATUS_PENDING_PAYMENT, ORDER_STATUS_PENDING_SHIPMENT]:
            return Response(
                {'error': '订单状态不正确，无法取消'},
                status=status.HTTP_400_BAD_REQUEST
            )

        cancel_reason = request.data.get('cancel_reason', '')

        with transaction.atomic():
            # 恢复库存
            for item in order.items.all():
                if item.sku:
                    item.sku.stock += item.quantity
                    item.sku.save()
                elif item.product:
                    item.product.stock += item.quantity
                    item.product.sales -= item.quantity
                    item.product.save()

            # 如果已发起过微信支付且还在待支付，尝试关闭微信订单
            if (order.status == ORDER_STATUS_PENDING_PAYMENT
                    and order.payment_method == PAYMENT_METHOD_WECHAT
                    and order.payment_no):
                try:
                    pay_helper = WeChatPayHelper()
                    pay_helper.cancel_payment_order(order.payment_no)
                    logger.info(f"取消订单时关闭微信支付: {order.payment_no}")
                except WeChatPayException as e:
                    logger.warning(f"关闭微信订单失败（继续取消）: {e}")

            order.status = ORDER_STATUS_CANCELLED
            order.cancel_reason = cancel_reason
            order.save()

        OrderLog.objects.create(
            order=order, action='CANCEL',
            description=f'订单取消，原因：{cancel_reason}', operator=request.user
        )
        return Response(OrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        order = self.get_object()
        if order.status not in [ORDER_STATUS_PENDING_SHIPMENT, ORDER_STATUS_SHIPPED]:
            return Response(
                {'error': '订单状态不正确，无法申请退款'},
                status=status.HTTP_400_BAD_REQUEST
            )
        refund_reason = request.data.get('refund_reason', '')
        order.status = ORDER_STATUS_REFUNDING
        order.save()
        OrderLog.objects.create(
            order=order, action='REFUND_APPLY',
            description=f'申请退款，原因：{refund_reason}', operator=request.user
        )
        return Response(OrderDetailSerializer(order).data)

    @action(detail=True, methods=['post'])
    def confirm_refund(self, request, pk=None):
        order = self.get_object()
        if order.status != ORDER_STATUS_REFUNDING:
            return Response({'error': '订单状态不正确'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            for item in order.items.all():
                if item.sku:
                    item.sku.stock += item.quantity
                    item.sku.save()
                elif item.product:
                    item.product.stock += item.quantity
                    item.product.sales -= item.quantity
                    item.product.save()

            order.status = ORDER_STATUS_REFUNDED
            order.save()

        OrderLog.objects.create(
            order=order, action='REFUND_CONFIRM',
            description='退款已确认', operator=request.user
        )
        return Response(OrderDetailSerializer(order).data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        queryset = self.get_queryset()
        return Response({
            'pending_payment': queryset.filter(status=ORDER_STATUS_PENDING_PAYMENT).count(),
            'pending_shipment': queryset.filter(status=ORDER_STATUS_PENDING_SHIPMENT).count(),
            'shipped': queryset.filter(status=ORDER_STATUS_SHIPPED).count(),
            'completed': queryset.filter(status=ORDER_STATUS_COMPLETED).count(),
            'refunding': queryset.filter(status=ORDER_STATUS_REFUNDING).count(),
        })


# ==================== 商城微信支付回调 ====================

def _mall_success_response():
    return HttpResponse(
        '<xml><return_code><![CDATA[SUCCESS]]></return_code>'
        '<return_msg><![CDATA[OK]]></return_msg></xml>',
        content_type='text/xml'
    )


def _mall_error_response(message):
    return HttpResponse(
        f'<xml><return_code><![CDATA[FAIL]]></return_code>'
        f'<return_msg><![CDATA[{message}]]></return_msg></xml>',
        content_type='text/xml'
    )


@csrf_exempt
def mall_wechat_callback(request):
    """
    商城微信支付回调

    POST /api/mall/wechat_callback/payment/

    收到微信支付结果通知，更新商城订单状态
    """
    if request.method != 'POST':
        return HttpResponse(status=405)

    try:
        pay_helper = WeChatPayHelper()
        xml_data = request.body

        # 1. 解析回调数据
        data = pay_helper.parse_callback(xml_data, callback_type='payment')

        # 2. 验证签名
        signature = data.get('sign')
        if not signature:
            logger.error("商城支付回调缺少签名")
            return _mall_error_response("Missing Signature")

        if not pay_helper.verify_signature(xml_data, signature):
            logger.error("商城支付回调签名验证失败")
            return _mall_error_response("Invalid Signature")

        # 3. 提取关键数据
        out_trade_no = data.get('out_trade_no')
        transaction_id = data.get('transaction_id')
        result_code = data.get('result_code')

        logger.info(
            f"📱 收到商城支付回调: "
            f"out_trade_no={out_trade_no}, "
            f"transaction_id={transaction_id}, "
            f"result_code={result_code}"
        )

        # 4. 查找商城订单（通过 payment_no 字段匹配 out_trade_no）
        try:
            order = Order.objects.get(
                payment_no=out_trade_no,
                status=ORDER_STATUS_PENDING_PAYMENT
            )
        except Order.DoesNotExist:
            # 可能已经处理过，查询所有状态
            if Order.objects.filter(payment_no=out_trade_no).exists():
                logger.info(f"商城订单已处理，跳过: out_trade_no={out_trade_no}")
                return _mall_success_response()
            else:
                logger.error(f"商城订单不存在: out_trade_no={out_trade_no}")
                return _mall_error_response("Order Not Found")

        # 5. 更新订单状态
        try:
            with transaction.atomic():
                if result_code == 'SUCCESS':
                    # 支付成功
                    order.status = ORDER_STATUS_PENDING_SHIPMENT
                    order.payment_no = transaction_id  # 更新为微信交易号
                    order.payment_time = timezone.now()
                    order.save()

                    # 记录日志
                    OrderLog.objects.create(
                        order=order,
                        action='PAY',
                        description=(
                            f'微信支付成功，交易号={transaction_id}，'
                            f'金额=¥{order.pay_amount}'
                        ),
                    )

                    logger.info(
                        f"✅ 商城支付成功: "
                        f"Order={order.order_no}, "
                        f"transaction_id={transaction_id}, "
                        f"amount=¥{order.pay_amount}"
                    )

                    # 清理用户缓存
                    cache_key = f"user_mall_orders:{order.user_id}"
                    cache.delete(cache_key)

                else:
                    # 支付失败 - 记录日志但不改变订单状态，用户可以重新支付
                    err_msg = data.get('err_code_des', '支付失败')
                    OrderLog.objects.create(
                        order=order,
                        action='PAY_FAIL',
                        description=f'微信支付失败，原因：{err_msg}',
                    )
                    logger.warning(
                        f"❌ 商城支付失败: Order={order.order_no}, 原因={err_msg}"
                    )

        except Exception as e:
            logger.error(f"处理商城支付回调失败: {e}", exc_info=True)
            return _mall_error_response("Internal Error")

        return _mall_success_response()

    except WeChatPayException as e:
        logger.error(f"商城微信支付回调异常: {e}", exc_info=True)
        return _mall_error_response("WeChatPay Exception")
    except Exception as e:
        logger.error(f"商城回调处理失败: {e}", exc_info=True)
        return _mall_error_response("Internal Error")


# ==================== 收藏视图 ====================

class FavoriteViewSet(viewsets.ModelViewSet):
    permission_classes = [IsUserOwner]
    authentication_classes = [UserAuthentication]
    serializer_class = ProductFavoriteSerializer
    pagination_class = SmallResultsSetPagination

    def get_queryset(self):
        return ProductFavorite.objects.filter(user=self.request.user).select_related('product')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        product_id = request.data.get('product')
        favorite, created = ProductFavorite.objects.get_or_create(
            user=request.user, product_id=product_id
        )
        if not created:
            return Response({'message': '已收藏过该商品'}, status=status.HTTP_200_OK)
        serializer = self.get_serializer(favorite)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def toggle(self, request):
        product_id = request.data.get('product_id')
        try:
            favorite = ProductFavorite.objects.get(user=request.user, product_id=product_id)
            favorite.delete()
            return Response({'is_favorited': False})
        except ProductFavorite.DoesNotExist:
            ProductFavorite.objects.create(user=request.user, product_id=product_id)
            return Response({'is_favorited': True})

    @action(detail=False, methods=['get'])
    def check(self, request):
        product_id = request.query_params.get('product_id')
        is_favorited = ProductFavorite.objects.filter(
            user=request.user, product_id=product_id
        ).exists()
        return Response({'is_favorited': is_favorited})