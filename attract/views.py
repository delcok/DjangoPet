from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response

from utils.authentication import ManagerAuthentication
from utils.permission import IsManager

from .models import HomepagePosition, HomepageSection
from .serializers import (
    HomepagePositionItemSerializer,
    AdminHomepagePositionSerializer, HomepageSectionSerializer, AdminHomepageSectionSerializer,
)


# ══════════════════════════════════════════════════════════
# 用户端（公开，无需认证）
# ══════════════════════════════════════════════════════════
class HomepagePositionListView(APIView):
    """
    GET /api/homepage/positions/?position=community_discount
    可选值: community_discount / super_recommend / special_group
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        position = request.query_params.get('position')
        if position not in HomepagePosition.Position.values:
            return Response(
                {'detail': '无效的 position 参数'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = list(HomepagePosition.objects.filter(
            position=position,
            is_active=True,
        ))

        # 按类型分组批量查询,避免 N+1
        goods_ids = [p.target_id for p in qs if p.target_type == HomepagePosition.TargetType.GOODS]
        service_ids = [p.target_id for p in qs if p.target_type == HomepagePosition.TargetType.SERVICE]

        goods_map, service_map = {}, {}
        if goods_ids:
            from product.models import Goods
            goods_map = Goods.objects.in_bulk(goods_ids)
        if service_ids:
            from services.models import Service  # ← 按实际 app 名改
            service_map = Service.objects.in_bulk(service_ids)

        # 组装返回数据
        data = []
        for p in qs:
            if p.target_type == HomepagePosition.TargetType.GOODS:
                obj = goods_map.get(p.target_id)
            else:
                obj = service_map.get(p.target_id)

            if not obj:
                continue  # 原商品/服务已删除,跳过

            data.append({
                'id': p.id,
                'target_type': p.target_type,
                'target_id': obj.id,
                # Goods 用 title，Service 用 name，做兼容
                'name': getattr(obj, 'name', None) or getattr(obj, 'title', ''),
                'cover': getattr(obj, 'cover_image', '') or getattr(obj, 'main_image', '') or '',
                'price': str(getattr(obj, 'price', '') or ''),
                'sort_order': p.sort_order,
            })

        serializer = HomepagePositionItemSerializer(data, many=True)
        return Response(serializer.data)


# ══════════════════════════════════════════════════════════
# 管理端（需管理员登录）
# ══════════════════════════════════════════════════════════
class AdminHomepagePositionViewSet(viewsets.ModelViewSet):
    """
    推荐位管理：增删改查
    - GET    /api/admin/homepage/positions/            列表(可筛选 position / target_type / is_active)
    - POST   /api/admin/homepage/positions/            创建
    - GET    /api/admin/homepage/positions/{id}/       详情
    - PUT    /api/admin/homepage/positions/{id}/       更新
    - PATCH  /api/admin/homepage/positions/{id}/       部分更新
    - DELETE /api/admin/homepage/positions/{id}/       删除
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    serializer_class = AdminHomepagePositionSerializer
    pagination_class = None  # 推荐位数量少,不分页

    def get_queryset(self):
        qs = HomepagePosition.objects.all()
        position = self.request.query_params.get('position')
        target_type = self.request.query_params.get('target_type')
        is_active = self.request.query_params.get('is_active')

        if position:
            qs = qs.filter(position=position)
        if target_type:
            qs = qs.filter(target_type=target_type)
        if is_active in ('true', '1'):
            qs = qs.filter(is_active=True)
        elif is_active in ('false', '0'):
            qs = qs.filter(is_active=False)
        return qs

# ══════════════════════════════════════════════════════════
# 用户端：板块标题（公开）
# ══════════════════════════════════════════════════════════
class HomepageSectionListView(APIView):
    """GET /api/homepage/sections/  返回三块区域的标题"""
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        HomepageSection.ensure_defaults()
        qs = HomepageSection.objects.all()
        return Response(HomepageSectionSerializer(qs, many=True).data)


# ══════════════════════════════════════════════════════════
# 管理端：板块标题编辑（只读列表 + 改，禁止增删）
# ══════════════════════════════════════════════════════════
class AdminHomepageSectionViewSet(viewsets.ModelViewSet):
    """
    - GET   /api/admin/homepage/sections/                列表(固定3条)
    - PATCH /api/admin/homepage/sections/{position}/     改标题
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    serializer_class = AdminHomepageSectionSerializer
    pagination_class = None
    lookup_field = 'position'
    http_method_names = ['get', 'put', 'patch', 'head', 'options']  # 不开放 post/delete

    def get_queryset(self):
        HomepageSection.ensure_defaults()
        return HomepageSection.objects.all()