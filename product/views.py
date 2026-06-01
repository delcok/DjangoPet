# goods/views.py

from django.db.models import F, Q, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from attract.models import HomepagePosition
from utils.authentication import (
    UserAuthentication,
    OptionalUserAuthentication,
    MerchantOrSubAuthentication,
    ManagerAuthentication,
)
from utils.permission import (
    AllowAny,
    IsAuthenticated,
    IsMerchant,
    IsManager,
    get_merchant_id_from_request,
)

from .models import (
    GoodsCategory, MerchantGoodsGroup, GoodsTag, Brand,
    Goods, GoodsSpec, GoodsSpecValue, GoodsSku,
    GoodsFavorite, GoodsViewHistory, GoodsCart,
)
from .serializers import (
    GoodsCategoryTreeSerializer, GoodsCategoryAdminSerializer,
    MerchantGoodsGroupSerializer,
    GoodsTagSerializer,
    BrandSerializer, BrandSimpleSerializer,
    GoodsListSerializer, GoodsDetailSerializer,
    MerchantGoodsListSerializer, MerchantGoodsDetailSerializer,
    MerchantGoodsCreateSerializer, MerchantGoodsUpdateSerializer,
    AdminGoodsListSerializer, AdminGoodsUpdateSerializer,
    AdminGoodsBatchSortSerializer,
    GoodsSpecSerializer, GoodsSpecCreateSerializer,
    GoodsSpecValueSerializer, GoodsSpecValueCreateSerializer,
    GoodsSkuSerializer, GoodsSkuCreateSerializer,
    GoodsFavoriteSerializer, MerchantBrandSerializer, CartItemSerializer, CartAddSerializer, CartUpdateSerializer,
)
from .filters import (
    GoodsFilter, GoodsCategoryFilter, BrandFilter,
    MerchantGoodsGroupFilter,
)
from .pagination import StandardPagination, SmallPagination


# ══════════════════════════════════════════════════════════════
# 商家身份提取 Mixin
# ══════════════════════════════════════════════════════════════

class MerchantMixin:
    """
    从 request.user 提取商家 ID，统一处理主账号/子账号两种身份。
    依赖 MerchantOrSubAuthentication 已经打好的标记。
    """

    def _get_merchant_id(self):
        """返回当前请求所属的商家 ID（主账号即自己，子账号取 merchant_id）"""
        return get_merchant_id_from_request(self.request)

    def _get_merchant(self):
        """返回当前请求所属的 Merchant 对象"""
        from merchants.models import Merchant
        mid = self._get_merchant_id()
        if not mid:
            raise serializers.ValidationError('无法识别商家身份')
        return Merchant.objects.get(id=mid)

    def _is_main_account(self):
        """是否为主账号"""
        return getattr(self.request.user, '_is_main_account', False)


# ══════════════════════════════════════════════════════════════
# ① 用户端公开接口（无需登录，明确跳过认证）
# ══════════════════════════════════════════════════════════════

class GoodsCategoryListView(generics.ListAPIView):
    """
    商品分类树（公开接口）

    GET /api/goods/categories/
    GET /api/goods/categories/?parent_id=0         一级分类
    GET /api/goods/categories/?is_show_home=true   首页分类
    """
    authentication_classes = []          # ★ 显式跳过全局认证，避免携带其他角色 token 时 401
    permission_classes = [AllowAny]
    serializer_class = GoodsCategoryTreeSerializer

    def get_queryset(self):
        qs = GoodsCategory.objects.filter(is_active=True)

        parent_id = self.request.query_params.get('parent_id')
        is_show_home = self.request.query_params.get('is_show_home')

        if is_show_home in ('true', '1'):
            qs = qs.filter(is_show_home=True)

        if parent_id is not None:
            if parent_id == '0':
                qs = qs.filter(parent__isnull=True)
            else:
                qs = qs.filter(parent_id=parent_id)
        else:
            # 默认返回一级分类（通过 serializer 的 children 字段递归输出子分类）
            qs = qs.filter(parent__isnull=True)

        return qs.order_by('sort_order', 'id')


class GoodsCategoryTreeView(generics.ListAPIView):
    """
    商品分类树（公开接口，专供首页金刚区/侧边导航/分类页使用）

    GET /api/goods/categories/tree/
        返回所有启用的一级分类（含子级树）

    GET /api/goods/categories/tree/?is_show_home=true
        仅返回标记为"首页展示"的一级分类 —— 金刚区主要用这个

    GET /api/goods/categories/tree/?limit=10
        限制一级分类数量（金刚区一般 8 / 10 个图标）

    GET /api/goods/categories/tree/?is_show_home=true&limit=10
        组合用，最常见
    """
    authentication_classes = []          # ★ 显式跳过全局认证
    permission_classes = [AllowAny]
    serializer_class = GoodsCategoryTreeSerializer
    pagination_class = None              # 树结构不分页，一次性返回

    def get_queryset(self):
        qs = GoodsCategory.objects.filter(
            is_active=True,
            parent__isnull=True,         # 只取一级，子级由 serializer 递归输出
        ).prefetch_related('children', 'children__children')

        if self.request.query_params.get('is_show_home') in ('true', '1'):
            qs = qs.filter(is_show_home=True)

        qs = qs.order_by('sort_order', 'id')

        limit = self.request.query_params.get('limit')
        if limit and limit.isdigit():
            qs = qs[: int(limit)]

        return qs

class BrandListView(generics.ListAPIView):
    """
    平台官方品牌列表（公开接口，不含商家私有品牌）

    GET /api/goods/brands/
    GET /api/goods/brands/?is_recommended=true
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = BrandSimpleSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = BrandFilter

    def get_queryset(self):
        return Brand.objects.filter(
            merchant__isnull=True,    # ★ 只返回平台官方品牌
            is_active=True,
        ).order_by('sort_order', 'id')


class GoodsTagListView(generics.ListAPIView):
    """
    平台公共标签列表（公开接口，不含商家私有标签）

    GET /api/goods/tags/
    """
    authentication_classes = []          # ★ 显式跳过
    permission_classes = [AllowAny]
    serializer_class = GoodsTagSerializer

    def get_queryset(self):
        return GoodsTag.objects.filter(
            merchant__isnull=True, is_active=True
        ).order_by('sort_order', 'id')


class GoodsListView(generics.ListAPIView):
    """
    商品列表（公开接口，只返回上架商品）

    GET /api/goods/
    GET /api/goods/?category_id=1&price_min=10&price_max=100
    GET /api/goods/?keyword=面膜&ordering=-sales
    """
    authentication_classes = []          # ★ 显式跳过
    permission_classes = [AllowAny]
    serializer_class = GoodsListSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = GoodsFilter
    pagination_class = StandardPagination

    def get_queryset(self):
        return Goods.objects.filter(
            status='on_sale'
        ).select_related(
            'category', 'brand', 'merchant', 'merchant_group'
        ).prefetch_related('tags').order_by(
            '-sort_order', '-created_at'
        )


class GoodsDetailView(generics.RetrieveAPIView):
    """
    商品详情（公开，但识别登录用户以记录浏览历史）

    GET /api/goods/{id}/
    """
    authentication_classes = [OptionalUserAuthentication]  # 有 user token 时识别，其他无声跳过
    permission_classes = [AllowAny]
    serializer_class = GoodsDetailSerializer

    def get_queryset(self):
        return Goods.objects.filter(
            status='on_sale'
        ).select_related(
            'category', 'brand', 'merchant'
        ).prefetch_related('tags', 'specs__values', 'skus')

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.increase_view()
        self._record_view_history(request, instance)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def _record_view_history(self, request, goods):
        """识别到已登录用户才记录"""
        user = getattr(request, 'user', None)
        if user and getattr(user, 'is_authenticated', False) and hasattr(user, 'id'):
            try:
                history, created = GoodsViewHistory.objects.get_or_create(
                    user=user, goods=goods,
                )
                if not created:
                    history.view_count += 1
                    history.save(update_fields=['view_count', 'last_view_at'])
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════
# ② 用户端需登录接口（收藏）
# ══════════════════════════════════════════════════════════════

class GoodsFavoriteView(APIView):
    """
    收藏 / 取消收藏

    POST   /api/goods/favorite/              body: {"goods": 1}
    DELETE /api/goods/favorite/{goods_id}/
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        goods_id = request.data.get('goods')
        if not goods_id:
            return Response({'error': '缺少商品ID'}, status=status.HTTP_400_BAD_REQUEST)
        if not Goods.objects.filter(id=goods_id, status='on_sale').exists():
            return Response({'error': '商品不存在或已下架'}, status=status.HTTP_404_NOT_FOUND)

        _, created = GoodsFavorite.objects.get_or_create(
            user=request.user, goods_id=goods_id
        )
        if created:
            Goods.objects.filter(pk=goods_id).update(
                favorite_count=F('favorite_count') + 1
            )
        return Response(
            {'message': '已收藏' if created else '已收藏过'},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    def delete(self, request, goods_id=None):
        deleted, _ = GoodsFavorite.objects.filter(
            user=request.user, goods_id=goods_id
        ).delete()
        if deleted:
            Goods.objects.filter(pk=goods_id).update(
                favorite_count=F('favorite_count') - 1
            )
        return Response({'message': '已取消收藏'})


class GoodsFavoriteListView(generics.ListAPIView):
    """
    我的收藏列表

    GET /api/goods/favorites/
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = GoodsFavoriteSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        return GoodsFavorite.objects.filter(
            user=self.request.user
        ).select_related('goods').order_by('-created_at')



# ══════════════════════════════════════════════════════════════
# ② 用户端 - 购物车
# ══════════════════════════════════════════════════════════════

class CartViewSet(viewsets.ModelViewSet):
    """
    商品购物车 (仅登录用户)

    GET    /api/goods/cart/                   - 列表(按商家分组 + 汇总)
    POST   /api/goods/cart/                   - 加入购物车 {sku, quantity}
    PATCH  /api/goods/cart/{id}/              - 修改 {quantity, is_selected}
    DELETE /api/goods/cart/{id}/              - 删除单条
    GET    /api/goods/cart/count/             - 总件数(角标用)
    GET    /api/goods/cart/selected/          - 已勾选可结算项(进入结算页)
    POST   /api/goods/cart/batch-delete/      - 批量删除 {ids: [1,2,3]}
    POST   /api/goods/cart/select-all/        - 全选/取消 {is_selected: true}
    POST   /api/goods/cart/clear-invalid/     - 一键清理失效项
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]
    pagination_class = None  # 购物车不分页,一次返回
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get_queryset(self):
        return GoodsCart.objects.filter(
            user=self.request.user
        ).select_related('goods', 'sku', 'merchant').order_by('-updated_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return CartAddSerializer
        if self.action == 'partial_update':
            return CartUpdateSerializer
        return CartItemSerializer

    # ─── 列表:按商家分组 + 汇总 ───
        # ─── 列表:按商家分组 + 汇总 ───
    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        items = CartItemSerializer(qs, many=True).data

        # ★ 收集商家 ID,一次性查商家配送配置
        from merchants.models import Merchant
        merchant_ids = list({i['merchant'] for i in items if i.get('merchant')})
        merchants_map = {
            m.id: m for m in Merchant.objects.filter(id__in=merchant_ids)
        } if merchant_ids else {}

        groups = {}
        for item in items:
            mid = item['merchant']
            if mid not in groups:
                m = merchants_map.get(mid)
                groups[mid] = {
                    'merchant_id': mid,
                    'merchant_name': item['merchant_name'],
                    'merchant_logo': item['merchant_logo'],
                    # ★ 商家配送配置(用于前端结算时判断走哪条路)
                    'support_home_delivery': bool(getattr(m, 'support_home_delivery', True)) if m else True,
                    'support_self_pickup': bool(getattr(m, 'support_self_pickup', False)) if m else False,
                    'pickup_address': getattr(m, 'full_address', '') if m else '',
                    'pickup_contact': getattr(m, 'contact_phone', '') if m else '',
                    'pickup_note': getattr(m, 'pickup_note', '') if m else '',
                    'items': [],
                }
            groups[mid]['items'].append(item)

        selected = [i for i in items if i['is_selected'] and i['is_valid']]
        total_amount = sum(
            float(i['current_price']) * i['quantity'] for i in selected
        )

        return Response({
            'groups': list(groups.values()),
            'total_count': len(items),
            'selected_count': len(selected),
            'total_amount': round(total_amount, 2),
            'max_items': GoodsCart.MAX_ITEMS,
        })

    # ─── 加入购物车 ───
    def create(self, request, *args, **kwargs):
        # 容量校验
        current_count = GoodsCart.objects.filter(user=request.user).count()
        if current_count >= GoodsCart.MAX_ITEMS:
            return Response(
                {'error': f'购物车最多容纳 {GoodsCart.MAX_ITEMS} 件商品,请先清理'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = CartAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sku = serializer.validated_data['sku']
        quantity = serializer.validated_data['quantity']

        cart_item, created = GoodsCart.objects.get_or_create(
            user=request.user,
            sku=sku,
            defaults={
                'goods': sku.goods,
                'merchant_id': sku.goods.merchant_id,
                'quantity': quantity,
                'snapshot_price': sku.price,
            }
        )
        if not created:
            new_quantity = cart_item.quantity + quantity
            if new_quantity > sku.stock:
                return Response(
                    {'error': f'加入失败,库存仅剩 {sku.stock}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if new_quantity > GoodsCart.MAX_QUANTITY_PER_SKU:
                return Response(
                    {'error': f'单个商品最多 {GoodsCart.MAX_QUANTITY_PER_SKU} 件'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            cart_item.quantity = new_quantity
            cart_item.is_selected = True
            cart_item.save(update_fields=['quantity', 'is_selected', 'updated_at'])

        return Response(
            CartItemSerializer(cart_item).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )

    # ─── 角标:购物车件数 ───
    @action(detail=False, methods=['get'])
    def count(self, request):
        total = GoodsCart.objects.filter(user=request.user).aggregate(
            n=Sum('quantity')
        )['n'] or 0
        return Response({'count': total})

    # ─── 已勾选项(结算用) ───
    @action(detail=False, methods=['get'])
    def selected(self, request):
        qs = self.get_queryset().filter(is_selected=True)
        valid_items = [c for c in qs if c.is_valid]
        data = CartItemSerializer(valid_items, many=True).data
        total = sum(float(i['current_price']) * i['quantity'] for i in data)
        return Response({
            'items': data,
            'total_count': len(data),
            'total_amount': round(total, 2),
        })

    # ─── 批量删除 ───
    @action(detail=False, methods=['post'], url_path='batch-delete')
    def batch_delete(self, request):
        ids = request.data.get('ids', [])
        if not isinstance(ids, list) or not ids:
            return Response(
                {'error': '请提供要删除的ID列表'},
                status=status.HTTP_400_BAD_REQUEST
            )
        deleted, _ = GoodsCart.objects.filter(
            user=request.user, id__in=ids
        ).delete()
        return Response({'deleted': deleted})

    # ─── 全选/取消 ───
    @action(detail=False, methods=['post'], url_path='select-all')
    def select_all(self, request):
        is_selected = bool(request.data.get('is_selected', True))
        GoodsCart.objects.filter(user=request.user).update(is_selected=is_selected)
        return Response({'message': '操作成功', 'is_selected': is_selected})

    # ─── 清理失效 ───
    @action(detail=False, methods=['post'], url_path='clear-invalid')
    def clear_invalid(self, request):
        qs = self.get_queryset()
        invalid_ids = [c.id for c in qs if not c.is_valid]
        if invalid_ids:
            GoodsCart.objects.filter(id__in=invalid_ids).delete()
        return Response({'deleted': len(invalid_ids)})
# ══════════════════════════════════════════════════════════════
# ③ 商家端接口（商家主账号 + 子账号都能通过）
# ══════════════════════════════════════════════════════════════

class MerchantGoodsViewSet(MerchantMixin, viewsets.ModelViewSet):
    """
    商家端 - 商品 CRUD

    GET    /api/merchant/goods/               列表
    POST   /api/merchant/goods/               创建
    GET    /api/merchant/goods/{id}/          详情
    PUT    /api/merchant/goods/{id}/          更新
    DELETE /api/merchant/goods/{id}/          删除
    POST   /api/merchant/goods/{id}/on_sale/  上架
    POST   /api/merchant/goods/{id}/off_sale/ 下架
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    filter_backends = [DjangoFilterBackend]
    filterset_class = GoodsFilter
    pagination_class = SmallPagination

    # ★ "进行中"商品订单状态(和服务订单保持一致原则: 非 终态 即进行中)
    #   终态: COMPLETED / CANCELLED / REFUNDED
    ACTIVE_PRODUCT_ORDER_STATUSES = [
        'pending_payment',   # 待支付(用户可能马上付)
        'paid',              # 已支付未发货
        'pending_shipment',  # 待发货
        'shipped',           # 已发货在途
        'received',          # 已收货(还可能退款/评价)
        'pending_pickup',    # 待自提
        'verified',          # 已核销(还差一步完成)
        'refunding',         # 退款中(等结果)
    ]

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        return Goods.objects.filter(
            merchant_id=merchant_id
        ).select_related(
            'category', 'brand', 'merchant_group'
        ).prefetch_related('tags', 'specs__values', 'skus').order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return MerchantGoodsListSerializer
        if self.action == 'create':
            return MerchantGoodsCreateSerializer
        if self.action in ['update', 'partial_update']:
            return MerchantGoodsUpdateSerializer
        return MerchantGoodsDetailSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['merchant'] = self._get_merchant()
        return ctx

    # ════════════════════════════════════════════════════════════
    # ↓↓↓ 新增:进行中订单检查工具
    # ════════════════════════════════════════════════════════════

    def _get_active_orders(self, goods_id):
        """返回该商品下进行中的订单 queryset(去重)"""
        from bill.models import ProductOrder
        return ProductOrder.objects.filter(
            items__product_id=goods_id,
            status__in=self.ACTIVE_PRODUCT_ORDER_STATUSES,
        ).distinct()

    def _check_active_orders_for_action(self, goods, action_name):
        """
        检查商品是否有进行中订单。
        有则返回 Response(直接 return 给上层),无则返回 None。
        """
        active_orders = self._get_active_orders(goods.id)
        active_count = active_orders.count()
        if active_count == 0:
            return None

        sample_order_nos = list(
            active_orders.order_by('-created_at')
            .values_list('order_no', flat=True)[:3]
        )
        return Response(
            {
                'error': f'该商品有 {active_count} 个进行中的订单，无法{action_name}',
                'detail': '请等订单完成、取消或退款后再操作',
                'active_count': active_count,
                'sample_order_nos': sample_order_nos,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ════════════════════════════════════════════════════════════
    # ↑↑↑ 新增结束
    # ════════════════════════════════════════════════════════════

    def destroy(self, request, *args, **kwargs):
        """删除 —— 有进行中订单时拒绝;否则清理广告位后删除"""
        instance = self.get_object()

        # 主动检查进行中订单(取代原来的 ProtectedError 兜底)
        block_response = self._check_active_orders_for_action(instance, '删除')
        if block_response:
            return block_response

        from django.db.models.deletion import ProtectedError
        goods_id = instance.id  # ★ 先存,delete 后 instance.id 会变 None
        title = instance.title

        try:
            instance.delete()
        except ProtectedError:
            # 进行中订单已经检查过,这里兜底处理其他 PROTECT 关联(如历史已完成订单)
            return Response(
                {'error': '该商品存在历史关联记录，无法删除，建议改为下架'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 同步清理首页广告位
        HomepagePosition.objects.filter(
            target_type=HomepagePosition.TargetType.GOODS,
            target_id=goods_id,
        ).delete()

        return Response(
            {'message': f'已删除「{title}」'},
            status=status.HTTP_200_OK
        )

    def partial_update(self, request, *args, **kwargs):
        """
        重写 PATCH:如果客户端直接通过 PATCH 把 status 改成 off_sale,
        也要走进行中订单检查(避免绕过 off_sale action)
        """
        instance = self.get_object()
        new_status = request.data.get('status')
        if (
            new_status == 'off_sale'
            and instance.status != 'off_sale'
        ):
            block_response = self._check_active_orders_for_action(instance, '下架')
            if block_response:
                return block_response
        return super().partial_update(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        """PUT 同上"""
        instance = self.get_object()
        new_status = request.data.get('status')
        if (
            new_status == 'off_sale'
            and instance.status != 'off_sale'
        ):
            block_response = self._check_active_orders_for_action(instance, '下架')
            if block_response:
                return block_response
        return super().update(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def on_sale(self, request, pk=None):
        """上架(必须有有效 SKU 且总库存 > 0)"""
        goods = self.get_object()
        if goods.total_stock <= 0:
            return Response(
                {'error': '库存为 0，请先设置 SKU 库存再上架'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not goods.skus.filter(is_active=True).exists():
            return Response(
                {'error': '请至少创建一个有效的 SKU 再上架'},
                status=status.HTTP_400_BAD_REQUEST
            )
        goods.status = 'on_sale'
        goods.published_at = timezone.now()
        goods.save(update_fields=['status', 'published_at', 'updated_at'])
        return Response({'message': '已上架'})

    @action(detail=True, methods=['post'])
    def off_sale(self, request, pk=None):
        """下架 —— 有进行中订单时拒绝"""
        goods = self.get_object()

        # ★ 进行中订单检查
        block_response = self._check_active_orders_for_action(goods, '下架')
        if block_response:
            return block_response

        goods.status = 'off_sale'
        goods.save(update_fields=['status', 'updated_at'])

        HomepagePosition.objects.filter(
            target_type=HomepagePosition.TargetType.GOODS,
            target_id=goods.id,
        ).delete()

        return Response({'message': '已下架'})
class MerchantGoodsGroupViewSet(MerchantMixin, viewsets.ModelViewSet):
    """
    商家端 - 店铺分组 CRUD

    GET    /api/merchant/goods-groups/
    POST   /api/merchant/goods-groups/
    PUT    /api/merchant/goods-groups/{id}/
    PATCH  /api/merchant/goods-groups/{id}/
    DELETE /api/merchant/goods-groups/{id}/
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    serializer_class = MerchantGoodsGroupSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = MerchantGoodsGroupFilter

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        return MerchantGoodsGroup.objects.filter(
            merchant_id=merchant_id
        ).order_by('sort_order', 'id')

    def perform_create(self, serializer):
        serializer.save(merchant=self._get_merchant())

    def destroy(self, request, *args, **kwargs):
        """真删除 —— 级联清理 SKU/规格/规格值/收藏/浏览记录"""
        from django.db.models.deletion import ProtectedError

        instance = self.get_object()
        title = instance.title
        goods_id = instance.id  # ★ 先存下来,delete 后 instance.id 会变 None

        try:
            instance.delete()
        except ProtectedError:
            return Response(
                {'error': '该商品存在历史订单，无法删除，建议改为下架'},
                status=status.HTTP_400_BAD_REQUEST
            )

        HomepagePosition.objects.filter(
            target_type=HomepagePosition.TargetType.GOODS,
            target_id=goods_id,
        ).delete()

        return Response(
            {'message': f'已删除「{title}」'},
            status=status.HTTP_200_OK
        )


class MerchantGoodsTagViewSet(MerchantMixin, viewsets.ModelViewSet):
    """
    商家端 - 私有标签管理

    GET    /api/merchant/goods-tags/
    POST   /api/merchant/goods-tags/
    PUT    /api/merchant/goods-tags/{id}/
    PATCH  /api/merchant/goods-tags/{id}/
    DELETE /api/merchant/goods-tags/{id}/
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    serializer_class = GoodsTagSerializer

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        return GoodsTag.objects.filter(
            merchant_id=merchant_id
        ).order_by('sort_order', 'id')

    def perform_create(self, serializer):
        serializer.save(merchant=self._get_merchant())


class MerchantBrandViewSet(MerchantMixin, viewsets.ModelViewSet):
    """
    商家端 - 私有品牌 CRUD

    GET    /api/merchant/goods-brands/                查询自己创建的品牌
    POST   /api/merchant/goods-brands/                创建品牌
    GET    /api/merchant/goods-brands/{id}/
    PUT    /api/merchant/goods-brands/{id}/
    PATCH  /api/merchant/goods-brands/{id}/
    DELETE /api/merchant/goods-brands/{id}/

    GET    /api/merchant/goods-brands/available/      可用品牌列表（平台官方 + 自己私有）
                                                       用于商品创建/编辑时的下拉选择
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]
    serializer_class = MerchantBrandSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = BrandFilter

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        return Brand.objects.filter(
            merchant_id=merchant_id
        ).order_by('sort_order', 'id')

    def perform_create(self, serializer):
        serializer.save(merchant=self._get_merchant())

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # 有商品正在使用此品牌时禁止删除
        if instance.goods.exists():
            raise serializers.ValidationError(
                '该品牌下还有商品，请先移除商品的品牌关联再删除'
            )
        name = instance.name
        instance.delete()
        return Response(
            {'message': f'已删除品牌「{name}」'},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=['get'], url_path='available')
    def available(self, request):
        """
        商家可用品牌列表（平台官方品牌 + 自己私有品牌，且均为启用状态）
        前端商品创建/编辑页的品牌下拉选择使用
        """
        merchant_id = self._get_merchant_id()
        qs = Brand.objects.filter(
            Q(merchant__isnull=True) | Q(merchant_id=merchant_id),
            is_active=True,
        ).order_by('merchant_id', 'sort_order', 'id')
        # 按 merchant_id 排序：NULL 在前（平台品牌优先展示），然后是自己的

        # 支持关键词搜索
        keyword = request.query_params.get('keyword', '').strip()
        if keyword:
            qs = qs.filter(name__icontains=keyword)

        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(
                BrandSimpleSerializer(page, many=True).data
            )
        return Response(BrandSimpleSerializer(qs, many=True).data)

# ── 嵌套：商品下的规格/规格值/SKU ─────────────────────────────

class MerchantGoodsSpecViewSet(MerchantMixin, viewsets.ModelViewSet):
    """
    商家端 - 商品规格名管理

    GET    /api/merchant/goods/{goods_id}/specs/
    POST   /api/merchant/goods/{goods_id}/specs/
    PUT    /api/merchant/goods/{goods_id}/specs/{id}/
    DELETE /api/merchant/goods/{goods_id}/specs/{id}/
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return GoodsSpecCreateSerializer
        return GoodsSpecSerializer

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        goods_id = self.kwargs.get('goods_id')
        return GoodsSpec.objects.filter(
            goods_id=goods_id,
            goods__merchant_id=merchant_id
        ).prefetch_related('values').order_by('sort_order', 'id')

    def perform_create(self, serializer):
        merchant_id = self._get_merchant_id()
        goods_id = self.kwargs.get('goods_id')
        try:
            goods = Goods.objects.get(id=goods_id, merchant_id=merchant_id)
        except Goods.DoesNotExist:
            raise serializers.ValidationError('商品不存在或无权操作')
        serializer.save(goods=goods)


class MerchantGoodsSpecValueViewSet(MerchantMixin, viewsets.ModelViewSet):
    """
    商家端 - 规格值管理

    GET    /api/merchant/goods/{goods_id}/specs/{spec_id}/values/
    POST   /api/merchant/goods/{goods_id}/specs/{spec_id}/values/
    PUT    /api/merchant/goods/{goods_id}/specs/{spec_id}/values/{id}/
    DELETE /api/merchant/goods/{goods_id}/specs/{spec_id}/values/{id}/
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return GoodsSpecValueCreateSerializer
        return GoodsSpecValueSerializer

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        spec_id = self.kwargs.get('spec_id')
        return GoodsSpecValue.objects.filter(
            spec_id=spec_id,
            spec__goods__merchant_id=merchant_id
        ).order_by('sort_order', 'id')

    def perform_create(self, serializer):
        merchant_id = self._get_merchant_id()
        spec_id = self.kwargs.get('spec_id')
        try:
            spec = GoodsSpec.objects.get(
                id=spec_id, goods__merchant_id=merchant_id
            )
        except GoodsSpec.DoesNotExist:
            raise serializers.ValidationError('规格不存在或无权操作')
        serializer.save(spec=spec)


class MerchantGoodsSkuViewSet(MerchantMixin, viewsets.ModelViewSet):
    """
    商家端 - SKU 管理
    增删改后会自动调用 goods.sync_stock() 同步 SPU 聚合数据。

    GET    /api/merchant/goods/{goods_id}/skus/
    POST   /api/merchant/goods/{goods_id}/skus/
    PUT    /api/merchant/goods/{goods_id}/skus/{id}/
    PATCH  /api/merchant/goods/{goods_id}/skus/{id}/
    DELETE /api/merchant/goods/{goods_id}/skus/{id}/
    """
    authentication_classes = [MerchantOrSubAuthentication]
    permission_classes = [IsMerchant]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return GoodsSkuCreateSerializer
        return GoodsSkuSerializer

    def get_queryset(self):
        merchant_id = self._get_merchant_id()
        goods_id = self.kwargs.get('goods_id')
        return GoodsSku.objects.filter(
            goods_id=goods_id,
            goods__merchant_id=merchant_id
        ).order_by('sort_order', 'id')

    def perform_create(self, serializer):
        merchant_id = self._get_merchant_id()
        goods_id = self.kwargs.get('goods_id')
        try:
            goods = Goods.objects.get(id=goods_id, merchant_id=merchant_id)
        except Goods.DoesNotExist:
            raise serializers.ValidationError('商品不存在或无权操作')
        serializer.save(goods=goods)
        goods.sync_stock()

    def perform_update(self, serializer):
        instance = serializer.save()
        instance.goods.sync_stock()

    def perform_destroy(self, instance):
        goods = instance.goods
        instance.delete()
        goods.sync_stock()


# ══════════════════════════════════════════════════════════════
# ④ 管理端接口（平台管理员）
# ══════════════════════════════════════════════════════════════

class AdminGoodsCategoryViewSet(viewsets.ModelViewSet):
    """
    管理端 - 商品分类 CRUD

    GET    /api/admin/categories/
    POST   /api/admin/categories/
    PUT    /api/admin/categories/{id}/
    DELETE /api/admin/categories/{id}/
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    serializer_class = GoodsCategoryAdminSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = GoodsCategoryFilter

    def get_queryset(self):
        return GoodsCategory.objects.all().order_by('sort_order', 'id')

    def perform_destroy(self, instance):
        if instance.children.exists():
            raise serializers.ValidationError('该分类下有子分类，不能删除')
        if instance.goods.exists():
            raise serializers.ValidationError('该分类下有商品，不能删除')
        instance.delete()


class AdminBrandViewSet(viewsets.ModelViewSet):
    """
    管理端 - 品牌 CRUD

    GET    /api/admin/brands/
    POST   /api/admin/brands/
    PUT    /api/admin/brands/{id}/
    DELETE /api/admin/brands/{id}/
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    serializer_class = BrandSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = BrandFilter

    def get_queryset(self):
        return Brand.objects.all().order_by('sort_order', 'id')


class AdminGoodsTagViewSet(viewsets.ModelViewSet):
    """
    管理端 - 平台公共标签 CRUD

    GET    /api/admin/tags/
    POST   /api/admin/tags/
    PUT    /api/admin/tags/{id}/
    DELETE /api/admin/tags/{id}/
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    serializer_class = GoodsTagSerializer

    def get_queryset(self):
        return GoodsTag.objects.filter(merchant__isnull=True).order_by('sort_order', 'id')

    def perform_create(self, serializer):
        serializer.save(merchant=None)


class AdminGoodsViewSet(viewsets.ModelViewSet):
    """
    管理端 - 商品管理（排序、推荐标记、状态）
    管理员不创建商品，只能调整排序/推荐标记/强制上下架。

    GET    /api/admin/goods/                    列表
    GET    /api/admin/goods/{id}/               详情
    PUT    /api/admin/goods/{id}/               更新排序/推荐/状态
    POST   /api/admin/goods/batch_sort/         批量排序
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    filter_backends = [DjangoFilterBackend]
    filterset_class = GoodsFilter
    pagination_class = SmallPagination
    http_method_names = ['get', 'put', 'patch', 'post', 'head', 'options']

    def get_serializer_class(self):
        if self.action == 'list':
            return AdminGoodsListSerializer
        if self.action in ['update', 'partial_update']:
            return AdminGoodsUpdateSerializer
        if self.action == 'batch_sort':
            return AdminGoodsBatchSortSerializer
        return MerchantGoodsDetailSerializer

    def get_queryset(self):
        return Goods.objects.all().select_related(
            'category', 'brand', 'merchant', 'merchant_group'
        ).prefetch_related('tags', 'specs__values', 'skus').order_by(
            '-sort_order', '-created_at'
        )

    def create(self, request, *args, **kwargs):
        return Response(
            {'error': '商品由商家创建，管理员仅可排序和推荐'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=False, methods=['post'])
    def batch_sort(self, request):
        """
        批量更新排序权重

        POST /api/admin/goods/batch_sort/
        body: {"items": [{"id": 1, "sort_order": 100}, {"id": 2, "sort_order": 90}]}
        """
        serializer = AdminGoodsBatchSortSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        items = serializer.validated_data['items']
        updated = 0
        for item in items:
            rows = Goods.objects.filter(id=item['id']).update(
                sort_order=item['sort_order']
            )
            updated += rows

        return Response({
            'message': f'已更新 {updated} 个商品的排序',
            'updated': updated,
        })


# ══════════════════════════════════════════════════════════════
# ② 用户端 - 运费 / 自提优惠预览(下单前调用)
# ══════════════════════════════════════════════════════════════

class FreightPreviewView(APIView):
    """
    运费 / 自提优惠预览

    POST /api/goods/freight-preview/
    body: {
        "merchant_id": 1,
        "delivery_type": "home_delivery" | "self_pickup",
        "address_id": 123,                          # 配送时必填
        "items": [{"sku_id": 10, "quantity": 2}, ...]
    }

    返回: {
        freight, goods_discount, distance_km,
        free_shipping_reason, subtotal, final_amount,
    }
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from decimal import Decimal
        from merchants.models import Merchant

        data = request.data
        merchant = Merchant.objects.filter(id=data.get('merchant_id')).first()
        if not merchant:
            return Response({'detail': '商家不存在'},
                            status=status.HTTP_404_NOT_FOUND)

        delivery_type = data.get('delivery_type', 'home_delivery')
        items_input = data.get('items') or []
        if not items_input:
            return Response({'detail': '请选择商品'},
                            status=status.HTTP_400_BAD_REQUEST)

        # —— 装配 items ——
        items = []
        for it in items_input:
            sku = (GoodsSku.objects
                   .select_related('goods')
                   .filter(id=it.get('sku_id')).first())
            if not sku:
                return Response(
                    {'detail': f"SKU {it.get('sku_id')} 不存在"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            items.append({
                'goods': sku.goods,
                'quantity': int(it.get('quantity', 1)),
                'price': sku.price,
            })

        # —— 收货坐标(仅配送需要) ——
        receiver_lat = receiver_lng = None
        if delivery_type == 'home_delivery':
            addr_id = data.get('address_id')
            if not addr_id:
                return Response({'detail': '请选择收货地址'},
                                status=status.HTTP_400_BAD_REQUEST)
            from address.models import UserAddress  # TODO: 路径按你实际调整
            addr = UserAddress.objects.filter(
                id=addr_id, user=request.user
            ).first()
            if not addr:
                return Response({'detail': '地址不存在'},
                                status=status.HTTP_400_BAD_REQUEST)
            if addr.latitude is None or addr.longitude is None:
                return Response({'detail': '该地址未定位,请重新选择'},
                                status=status.HTTP_400_BAD_REQUEST)
            receiver_lat, receiver_lng = addr.latitude, addr.longitude

        # —— 调用 Merchant.calc_freight 算钱 ——
        result = merchant.calc_freight(
            items=items, delivery_type=delivery_type,
            receiver_lat=receiver_lat, receiver_lng=receiver_lng,
        )
        if not result['ok']:
            return Response({'detail': result['error']},
                            status=status.HTTP_400_BAD_REQUEST)

        subtotal = sum(
            (Decimal(str(it['price'])) * it['quantity'] for it in items),
            Decimal('0'),
        )
        final_amount = (
                subtotal + result['freight'] - result['goods_discount']
        ).quantize(Decimal('0.01'))

        return Response({
            'freight': str(result['freight']),
            'goods_discount': str(result['goods_discount']),
            'distance_km': result['distance_km'],
            'free_shipping_reason': result['free_shipping_reason'],
            'subtotal': str(subtotal),
            'final_amount': str(final_amount),
        })