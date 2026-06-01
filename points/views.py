from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action
from rest_framework.response import Response

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from datetime import timedelta

from django_filters.rest_framework import DjangoFilterBackend

from utils.authentication import UserAuthentication, ManagerAuthentication
from utils.permission import IsUser, IsManager
from user.models import User
from wallet.models import UserWallet, WalletTransaction, Currency
from .models import (
    IntegralProduct, IntegralOrder, UserIntegralProduct
)
from .serializers import (
    IntegralProductListSerializer, IntegralProductDetailSerializer,
    IntegralOrderCreateSerializer, IntegralOrderSerializer,
    UserIntegralProductSerializer, PointsTransactionSerializer,
    IntegralProductAdminSerializer, IntegralOrderAdminSerializer,
)
from .filters import (
    IntegralProductFilter, IntegralOrderFilter, PointsTransactionFilter,
)


def get_user_wallet(user):
    """获取（或初始化）用户钱包。积分余额/流水都以钱包为准。"""
    wallet, _ = UserWallet.objects.get_or_create(user=user)
    return wallet


# ==========================================================================
# 用户端（C 端）
# ==========================================================================

class IntegralProductViewSet(viewsets.ReadOnlyModelViewSet):
    """积分商品视图集

    基础 queryset 仅含上架商品；类型/分类/是否热门等筛选交给 IntegralProductFilter
    （兼容旧的 ?type= / ?category= / ?is_hot=true / ?is_new=true）。
    """

    queryset = IntegralProduct.objects.filter(status='on_sale')
    permission_classes = [IsUser]  # 原 IsUserClient 在新权限体系不存在，统一为 IsUser
    authentication_classes = [UserAuthentication]
    filter_backends = [DjangoFilterBackend]
    filterset_class = IntegralProductFilter

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return IntegralProductDetailSerializer
        return IntegralProductListSerializer

    @action(detail=False, methods=['get'])
    def categories(self, request):
        """获取商品分类列表"""
        categories = IntegralProduct.objects.filter(
            status='on_sale'
        ).values_list('category', flat=True).distinct()
        return Response({'categories': list(categories)})


class IntegralOrderViewSet(viewsets.ModelViewSet):
    """积分订单视图集（用户端）

    用户只能：创建兑换订单、查看自己的订单、确认收货、取消待发货订单。
    订单创建后不允许任意改/删（http_method_names 已禁用 PUT/PATCH/DELETE），
    避免用户通过 PATCH 篡改 status / integral_cost 等字段。
    后台的发货/完成/取消在 AdminIntegralOrderViewSet。

    积分扣减/退还统一走用户钱包 UserWallet.change_points()，会自动写 WalletTransaction。
    列表筛选（状态/时间区间/排序）交给 IntegralOrderFilter。
    """

    serializer_class = IntegralOrderSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]
    http_method_names = ['get', 'post', 'head', 'options']
    filter_backends = [DjangoFilterBackend]
    filterset_class = IntegralOrderFilter

    def get_queryset(self):
        return IntegralOrder.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        """创建兑换订单"""
        serializer = IntegralOrderCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                # 锁商品，避免并发超卖（积分余额由钱包内部加锁保证）
                product = IntegralProduct.objects.select_for_update().get(
                    pk=serializer.validated_data['product'].pk
                )
                quantity = serializer.validated_data['quantity']
                total_integral = product.integral_price * quantity

                # 锁内复核库存
                if not product.is_available or product.stock < quantity:
                    return Response(
                        {'error': '商品已下架或库存不足'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # 创建商品快照
                product_snapshot = {
                    'name': product.name,
                    'cover_image': product.cover_image,
                    'integral_price': product.integral_price,
                    'product_type': product.product_type,
                }

                # 创建订单
                order = IntegralOrder.objects.create(
                    user=request.user,
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

                    expired_at = None
                    if product.validity_days > 0:
                        expired_at = timezone.now() + timedelta(days=product.validity_days)

                    UserIntegralProduct.objects.create(
                        user=request.user,
                        product=product,
                        order=order,
                        content=product.virtual_content,
                        expired_at=expired_at
                    )

                # 扣减库存
                product.reduce_stock(quantity)

                # 扣减积分 —— 走用户钱包（自动写 WalletTransaction，钱包内部加锁+复核余额）
                wallet = get_user_wallet(request.user)
                wallet.change_points(
                    -total_integral,
                    action=WalletTransaction.Action.EXCHANGE,
                    operator_id=request.user.id,
                    operator_role='user',
                    related_type='integral_order',
                    related_id=order.id,
                    remark=f'兑换商品：{product.name}',
                    idempotent_key=f'integral_exchange_{order.id}',
                )
        except ValueError as e:
            # 钱包抛出的「积分不足 / 钱包冻结 / 钱包暂停」等
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

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
        """取消订单（待发货可取消，退还积分与库存）"""
        order = self.get_object()

        if order.status not in ['pending']:
            return Response(
                {'error': '该订单无法取消'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                locked = IntegralOrder.objects.select_for_update().get(pk=order.pk)
                if locked.status != 'pending':
                    return Response(
                        {'error': '该订单无法取消'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                locked.status = 'cancelled'
                locked.cancelled_at = timezone.now()
                locked.save(update_fields=['status', 'cancelled_at'])

                # 恢复库存
                locked.product.restore_stock(locked.quantity)

                # 退还积分 —— 走钱包
                wallet = get_user_wallet(locked.user)
                wallet.change_points(
                    locked.integral_cost,
                    action=WalletTransaction.Action.REFUND_RETURN,
                    operator_id=request.user.id,
                    operator_role='user',
                    related_type='integral_order',
                    related_id=locked.id,
                    remark=f'取消订单退还：{locked.product.name}',
                    idempotent_key=f'integral_refund_{locked.id}',
                )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'message': '取消订单成功'})


class IntegralRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """积分记录视图集（读钱包流水 WalletTransaction，仅积分币种）

    动作/方向/金额区间/时间区间/排序交给 PointsTransactionFilter
    （兼容旧的 ?type= -> 现用 ?action=）。
    """

    serializer_class = PointsTransactionSerializer
    permission_classes = [IsUser]
    authentication_classes = [UserAuthentication]
    filter_backends = [DjangoFilterBackend]
    filterset_class = PointsTransactionFilter

    def get_queryset(self):
        return WalletTransaction.objects.filter(
            user_id=self.request.user.id,
            currency=Currency.POINTS,
        ).order_by('-created_at')

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """积分统计（直接读钱包累计字段）"""
        wallet = get_user_wallet(request.user)
        return Response({
            'current_integral': wallet.points_balance,
            'points_available': wallet.points_available,
            'total_earn': wallet.points_total_earned,
            'total_consume': wallet.points_total_spent,
        })


class UserIntegralProductViewSet(viewsets.ReadOnlyModelViewSet):
    """用户虚拟商品视图集"""

    serializer_class = UserIntegralProductSerializer
    permission_classes = [IsUser]
    authentication_classes = [UserAuthentication]

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


# ==========================================================================
# 平台后台（Manager）
# ==========================================================================

class AdminIntegralProductViewSet(viewsets.ModelViewSet):
    """积分商品管理（平台后台）

    走 ManagerAuthentication + IsManager。提供商品的增删改查，并附：
    - POST {id}/on_sale/   上架
    - POST {id}/off_sale/  下架
    - POST {id}/restock/   补货（body: {"amount": N}）

    列表筛选（状态/类型/价格区间/库存/关键词/时间/排序）交给 IntegralProductFilter。
    """
    queryset = IntegralProduct.objects.all().order_by('-sort_order', '-created_at')
    serializer_class = IntegralProductAdminSerializer
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filter_backends = [DjangoFilterBackend]
    filterset_class = IntegralProductFilter

    @action(detail=True, methods=['post'])
    def on_sale(self, request, pk=None):
        """上架（无库存则置为售罄）"""
        product = self.get_object()
        product.status = 'on_sale' if product.stock > 0 else 'sold_out'
        product.save(update_fields=['status'])
        return Response({'message': '已上架', 'status': product.status})

    @action(detail=True, methods=['post'])
    def off_sale(self, request, pk=None):
        """下架"""
        product = self.get_object()
        product.status = 'off_sale'
        product.save(update_fields=['status'])
        return Response({'message': '已下架', 'status': 'off_sale'})

    @action(detail=True, methods=['post'])
    def restock(self, request, pk=None):
        """补货：增加库存（amount 为正整数）"""
        product = self.get_object()
        try:
            amount = int(request.data.get('amount'))
        except (TypeError, ValueError):
            return Response({'error': 'amount 必须是整数'}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= 0:
            return Response({'error': 'amount 必须大于 0'}, status=status.HTTP_400_BAD_REQUEST)

        product.stock += amount
        product.total_stock += amount
        if product.status == 'sold_out' and product.stock > 0:
            product.status = 'on_sale'
        product.save(update_fields=['stock', 'total_stock', 'status'])
        return Response({'message': '补货成功', 'stock': product.stock})


class AdminIntegralOrderViewSet(mixins.ListModelMixin,
                                mixins.RetrieveModelMixin,
                                viewsets.GenericViewSet):
    """积分订单管理（平台后台）

    查看全部订单，筛选（状态/用户/订单号/快递/时间区间/排序）交给 IntegralOrderFilter，
    并提供状态流转动作：
    - POST {id}/ship/      发货（实物，body: {"express_company","express_no","admin_remark"?}）
    - POST {id}/complete/  手动完成（已发货 -> 已完成）
    - POST {id}/cancel/    取消并退还积分/库存（待发货或已发货均可）
    """
    serializer_class = IntegralOrderAdminSerializer
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filter_backends = [DjangoFilterBackend]
    filterset_class = IntegralOrderFilter

    def get_queryset(self):
        return IntegralOrder.objects.select_related(
            'user', 'product', 'address'
        ).order_by('-created_at')

    @action(detail=True, methods=['post'])
    def ship(self, request, pk=None):
        """发货（仅实物、仅待发货）"""
        order = self.get_object()
        if order.product.product_type != 'physical':
            return Response({'error': '虚拟商品无需发货'}, status=status.HTTP_400_BAD_REQUEST)
        if order.status != 'pending':
            return Response({'error': '只有待发货订单可以发货'}, status=status.HTTP_400_BAD_REQUEST)

        express_company = request.data.get('express_company', '')
        express_no = request.data.get('express_no', '')
        if not express_company or not express_no:
            return Response({'error': '请填写快递公司和快递单号'}, status=status.HTTP_400_BAD_REQUEST)

        order.status = 'shipped'
        order.express_company = express_company
        order.express_no = express_no
        order.shipped_at = timezone.now()
        if 'admin_remark' in request.data:
            order.admin_remark = request.data['admin_remark']
        order.save(update_fields=[
            'status', 'express_company', 'express_no', 'shipped_at', 'admin_remark'
        ])
        return Response({'message': '发货成功'})

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """手动完成订单（已发货 -> 已完成）"""
        order = self.get_object()
        if order.status != 'shipped':
            return Response({'error': '只有已发货订单可以完成'}, status=status.HTTP_400_BAD_REQUEST)
        order.status = 'completed'
        order.completed_at = timezone.now()
        order.save(update_fields=['status', 'completed_at'])
        return Response({'message': '订单已完成'})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """后台取消订单并退还积分/库存（待发货或已发货均可）"""
        order = self.get_object()
        if order.status in ['completed', 'cancelled']:
            return Response({'error': '该订单无法取消'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                locked = IntegralOrder.objects.select_for_update().get(pk=order.pk)
                if locked.status in ['completed', 'cancelled']:
                    return Response({'error': '该订单无法取消'}, status=status.HTTP_400_BAD_REQUEST)

                locked.status = 'cancelled'
                locked.cancelled_at = timezone.now()
                if 'admin_remark' in request.data:
                    locked.admin_remark = request.data['admin_remark']
                locked.save(update_fields=['status', 'cancelled_at', 'admin_remark'])

                # 恢复库存
                locked.product.restore_stock(locked.quantity)

                # 退还积分 —— 走钱包
                wallet = get_user_wallet(locked.user)
                wallet.change_points(
                    locked.integral_cost,
                    action=WalletTransaction.Action.REFUND_RETURN,
                    operator_id=request.user.id,
                    operator_role='admin',
                    related_type='integral_order',
                    related_id=locked.id,
                    remark=f'后台取消订单退还：{locked.product.name}',
                    idempotent_key=f'integral_refund_{locked.id}',
                )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'message': '订单已取消，积分与库存已退还'})


class AdminIntegralRecordViewSet(mixins.ListModelMixin,
                                 mixins.RetrieveModelMixin,
                                 viewsets.GenericViewSet):
    """积分流水管理（平台后台，读钱包 WalletTransaction，仅积分币种）

    查看全部积分流水，筛选（用户/动作/方向/金额区间/时间区间/排序）交给
    PointsTransactionFilter，并提供：
    - POST adjust/       人工调整用户积分（body: {"user_id","amount","description"?}，amount 正负皆可）
    - GET  statistics/   积分整体统计看板
    """
    serializer_class = PointsTransactionSerializer
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filter_backends = [DjangoFilterBackend]
    filterset_class = PointsTransactionFilter

    def get_queryset(self):
        return WalletTransaction.objects.filter(
            currency=Currency.POINTS
        ).order_by('-created_at')

    @action(detail=False, methods=['post'])
    def adjust(self, request):
        """人工调整用户积分（amount 正负皆可；走钱包，自动写 WalletTransaction）"""
        user_id = request.data.get('user_id')
        description = request.data.get('description') or '管理员调整'
        try:
            amount = int(request.data.get('amount'))
        except (TypeError, ValueError):
            return Response({'error': 'amount 必须是整数'}, status=status.HTTP_400_BAD_REQUEST)
        if amount == 0:
            return Response({'error': 'amount 不能为 0'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({'error': '用户不存在'}, status=status.HTTP_404_NOT_FOUND)

        wallet = get_user_wallet(user)
        action_type = (
            WalletTransaction.Action.ADMIN_GRANT if amount > 0
            else WalletTransaction.Action.ADMIN_DEDUCT
        )
        try:
            tx = wallet.change_points(
                amount,
                action=action_type,
                operator_id=request.user.id,
                operator_role='admin',
                remark=description,
            )
        except ValueError as e:
            # 扣减时余额不足等
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': '调整成功',
            'user_id': user.id,
            'amount': amount,
            'balance': tx.balance_after,
            'transaction_id': tx.id,
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """积分整体统计看板（基于钱包积分流水）"""
        qs = WalletTransaction.objects.filter(
            currency=Currency.POINTS,
            status=WalletTransaction.Status.NORMAL,
        )
        total_in = qs.filter(amount__gt=0).aggregate(t=Sum('amount'))['t'] or 0
        total_out = abs(qs.filter(amount__lt=0).aggregate(t=Sum('amount'))['t'] or 0)
        return Response({
            'total_points_in': total_in,
            'total_points_out': total_out,
            'order_count': IntegralOrder.objects.count(),
            'pending_ship': IntegralOrder.objects.filter(status='pending').count(),
        })