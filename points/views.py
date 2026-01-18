from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.db.models import Sum  # 添加这一行
from django.utils import timezone
from datetime import timedelta

from .models import (
    IntegralProduct, IntegralOrder, IntegralRecord,
    UserIntegralProduct
)
from .serializers import (
    IntegralProductListSerializer, IntegralProductDetailSerializer,
    IntegralOrderCreateSerializer, IntegralOrderSerializer,
    IntegralRecordSerializer, UserIntegralProductSerializer
)


class IntegralProductViewSet(viewsets.ReadOnlyModelViewSet):
    """积分商品视图集"""

    queryset = IntegralProduct.objects.filter(status='on_sale')
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return IntegralProductDetailSerializer
        return IntegralProductListSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        product_type = self.request.query_params.get('type')
        category = self.request.query_params.get('category')
        is_hot = self.request.query_params.get('is_hot')
        is_new = self.request.query_params.get('is_new')

        if product_type:
            queryset = queryset.filter(product_type=product_type)
        if category:
            queryset = queryset.filter(category=category)
        if is_hot == 'true':
            queryset = queryset.filter(is_hot=True)
        if is_new == 'true':
            queryset = queryset.filter(is_new=True)

        return queryset

    @action(detail=False, methods=['get'])
    def categories(self, request):
        """获取商品分类列表"""
        categories = IntegralProduct.objects.filter(
            status='on_sale'
        ).values_list('category', flat=True).distinct()
        return Response({'categories': list(categories)})


class IntegralOrderViewSet(viewsets.ModelViewSet):
    """积分订单视图集"""

    serializer_class = IntegralOrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return IntegralOrder.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        """创建兑换订单"""
        serializer = IntegralOrderCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            # 获取验证后的数据
            product = serializer.validated_data['product']
            quantity = serializer.validated_data['quantity']
            total_integral = serializer.validated_data['total_integral']
            user = request.user

            # 创建商品快照
            product_snapshot = {
                'name': product.name,
                'cover_image': product.cover_image,
                'integral_price': product.integral_price,
                'product_type': product.product_type,
            }

            # 创建订单
            order = IntegralOrder.objects.create(
                user=user,
                product=product,
                product_snapshot=product_snapshot,
                quantity=quantity,
                integral_cost=total_integral,
                user_remark=serializer.validated_data.get('user_remark', '')
            )

            # 处理收货地址（实物商品）
            if product.product_type == 'physical':
                address = serializer.validated_data['address']
                order.address = address
                order.receiver_name = address.receiver_name
                order.receiver_phone = address.receiver_phone
                order.receiver_address = (
                    f"{address.province}{address.city}{address.district}"
                    f"{address.detail_address}"
                )
                order.save()
            else:
                # 虚拟商品自动完成
                order.status = 'completed'
                order.completed_at = timezone.now()
                order.save()

                # 创建虚拟商品记录
                expired_at = None
                if product.validity_days > 0:
                    expired_at = timezone.now() + timedelta(days=product.validity_days)

                UserIntegralProduct.objects.create(
                    user=user,
                    product=product,
                    order=order,
                    content=product.virtual_content,
                    expired_at=expired_at
                )

            # 扣减库存
            product.reduce_stock(quantity)

            # 扣减积分
            user.integral -= total_integral
            user.save(update_fields=['integral'])

            # 记录积分变动
            IntegralRecord.objects.create(
                user=user,
                record_type='consume',
                source='exchange',
                amount=-total_integral,
                balance=user.integral,
                order=order,
                description=f"兑换商品：{product.name}"
            )

        return Response(
            IntegralOrderSerializer(order).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'])
    def confirm_receipt(self, request, pk=None):
        """确认收货"""
        order = self.get_object()

        if order.status != 'shipped':
            return Response(
                {'error': '订单状态不正确'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order.status = 'completed'
        order.completed_at = timezone.now()
        order.save()

        return Response({'message': '确认收货成功'})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """取消订单"""
        order = self.get_object()

        if order.status not in ['pending']:
            return Response(
                {'error': '该订单无法取消'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # 更新订单状态
            order.status = 'cancelled'
            order.cancelled_at = timezone.now()
            order.save()

            # 恢复库存
            order.product.restore_stock(order.quantity)

            # 退还积分
            user = order.user
            user.integral += order.integral_cost
            user.save(update_fields=['integral'])

            # 记录积分变动
            IntegralRecord.objects.create(
                user=user,
                record_type='refund',
                source='refund',
                amount=order.integral_cost,
                balance=user.integral,
                order=order,
                description=f"取消订单退还：{order.product.name}"
            )

        return Response({'message': '取消订单成功'})


class IntegralRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """积分记录视图集"""

    serializer_class = IntegralRecordSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = IntegralRecord.objects.filter(user=self.request.user)
        record_type = self.request.query_params.get('type')
        if record_type:
            queryset = queryset.filter(record_type=record_type)
        return queryset

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """积分统计"""
        user = request.user
        records = IntegralRecord.objects.filter(user=user)

        # 修正这里：使用 Sum 而不是 models.Sum
        total_earn = records.filter(record_type='earn').aggregate(
            total=Sum('amount')
        )['total'] or 0

        total_consume = abs(records.filter(record_type='consume').aggregate(
            total=Sum('amount')
        )['total'] or 0)

        return Response({
            'current_integral': user.integral,
            'total_earn': total_earn,
            'total_consume': total_consume,
        })


class UserIntegralProductViewSet(viewsets.ReadOnlyModelViewSet):
    """用户虚拟商品视图集"""

    serializer_class = UserIntegralProductSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserIntegralProduct.objects.filter(user=self.request.user)

    @action(detail=True, methods=['post'])
    def use(self, request, pk=None):
        """使用虚拟商品"""
        virtual_product = self.get_object()

        if virtual_product.use():
            return Response({'message': '使用成功'})
        else:
            return Response(
                {'error': '商品已使用或已过期'},
                status=status.HTTP_400_BAD_REQUEST
            )