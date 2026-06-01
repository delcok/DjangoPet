# addresses/views.py
"""
用户地址管理视图
- 用户端：自己的地址 CRUD，最多20条，设置默认地址
- 管理端：查看所有用户地址（只读 + 搜索）
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from .models import UserAddress
from .serializers import (
    UserAddressSerializer,
    UserAddressSimpleSerializer,
    UserAddressAdminSerializer,
)
from .filters import UserAddressFilter, UserAddressAdminFilter
from .paginations import AddressPagination, AddressAdminPagination
from utils.authentication import UserAuthentication, ManagerAuthentication
from utils.permission import IsUser, IsManager

# 单个用户最多地址数
MAX_ADDRESS_PER_USER = 20


# ══════════════════════════════════════════════════════════════
# 用户端 — 地址管理
# ══════════════════════════════════════════════════════════════

class UserAddressViewSet(viewsets.ModelViewSet):
    """
    用户端 - 收货地址 CRUD

    GET    /api/user/addresses/              地址列表
    POST   /api/user/addresses/              新增地址
    GET    /api/user/addresses/{id}/         地址详情
    PUT    /api/user/addresses/{id}/         更新地址
    DELETE /api/user/addresses/{id}/         删除地址
    POST   /api/user/addresses/{id}/default/ 设为默认
    GET    /api/user/addresses/default/      获取默认地址
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]
    pagination_class = AddressPagination
    filter_backends = [DjangoFilterBackend]
    filterset_class = UserAddressFilter

    def get_queryset(self):
        """只能看到自己的地址"""
        return UserAddress.objects.filter(
            user=self.request.user
        ).order_by('-is_default', '-updated_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return UserAddressSimpleSerializer
        return UserAddressSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def create(self, request, *args, **kwargs):
        """新增地址（限制总数）"""
        count = UserAddress.objects.filter(user=request.user).count()
        if count >= MAX_ADDRESS_PER_USER:
            return Response(
                {'error': f'最多保存{MAX_ADDRESS_PER_USER}条地址，请删除不用的地址后再添加'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().create(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """删除地址"""
        instance.delete()

    @action(detail=True, methods=['post'], url_path='set-default')
    def set_default(self, request, pk=None):
        """设为默认地址"""
        address = self.get_object()

        # 取消其他默认
        UserAddress.objects.filter(
            user=request.user, is_default=True
        ).exclude(pk=address.pk).update(is_default=False)

        address.is_default = True
        address.save(update_fields=['is_default', 'updated_at'])

        return Response({'message': '已设为默认地址'})

    @action(detail=False, methods=['get'], url_path='default')
    def get_default(self, request):
        """
        获取默认地址
        如果没有默认地址，返回最近更新的一条
        """
        address = UserAddress.objects.filter(
            user=request.user
        ).order_by('-is_default', '-updated_at').first()

        if not address:
            return Response(
                {'error': '暂无收货地址'},
                status=status.HTTP_404_NOT_FOUND
            )

        return Response(UserAddressSerializer(address).data)

