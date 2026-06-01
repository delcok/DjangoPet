# managers/views.py
"""
管理员视图
使用项目已有的 authentication.py 和 permissions.py
"""

from datetime import datetime
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Manager, ManagerRole, ManagerOperationLog, SystemConfig
from .serializers import (
    ManagerLoginSerializer, ManagerChangePasswordSerializer,
    ManagerRoleSerializer, ManagerRoleSimpleSerializer,
    ManagerListSerializer, ManagerDetailSerializer,
    ManagerCreateSerializer, ManagerUpdateSerializer,
    ManagerProfileSerializer, ManagerProfileUpdateSerializer,
    ManagerOperationLogSerializer, ManagerOperationLogDetailSerializer,
    SystemConfigSerializer,  SystemConfigBatchUpdateSerializer
)

# 使用项目已有的认证和权限
from utils.authentication import ManagerAuthentication, generate_manager_tokens
from utils.permission import AllowAny, IsManager
from utils.cache import LoginSecurityManager
from .paginations import AdminPagination


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def get_client_ip(request):
    """获取客户端IP"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def log_operation(manager, action_type, module, description, request=None, **kwargs):
    """记录操作日志"""
    log_data = {
        'manager': manager,
        'manager_name': manager.name,
        'manager_username': manager.username,
        'action': action_type,
        'module': module,
        'description': description,
        **kwargs
    }

    if request:
        log_data['ip_address'] = get_client_ip(request)
        log_data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')[:500]

    return ManagerOperationLog.objects.create(**log_data)


# ══════════════════════════════════════════════════════════════
# 认证相关
# ══════════════════════════════════════════════════════════════

class ManagerLoginView(APIView):
    """管理员登录"""
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ManagerLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        security = LoginSecurityManager()

        # 检查是否被锁定
        is_locked, remaining = security.is_locked(username, 'manager')
        if is_locked:
            minutes = remaining // 60 + 1
            return Response(
                {'error': f'账户已锁定，请{minutes}分钟后重试'},
                status=status.HTTP_403_FORBIDDEN
            )

        # 查找管理员
        try:
            manager = Manager.objects.select_related('role').get(username=username)
        except Manager.DoesNotExist:
            return Response(
                {'error': '用户名或密码错误'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 验证密码
        if not manager.check_password(password):
            fail_count, locked = security.record_fail(username, 'manager')
            if locked:
                return Response(
                    {'error': '密码错误次数过多，账户已锁定30分钟'},
                    status=status.HTTP_403_FORBIDDEN
                )
            remaining_attempts = security.get_remaining_attempts(username, 'manager')
            return Response(
                {'error': f'密码错误，还剩{remaining_attempts}次机会'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 检查状态
        if not manager.is_active:
            return Response(
                {'error': '账户已被禁用'},
                status=status.HTTP_403_FORBIDDEN
            )

        # 登录成功
        security.clear_fail_count(username, 'manager')

        # 更新登录信息
        manager.last_login = datetime.now()
        manager.last_login_ip = get_client_ip(request)
        manager.login_fail_count = 0
        manager.save(update_fields=['last_login', 'last_login_ip', 'login_fail_count'])

        # 记录登录日志
        log_operation(
            manager=manager,
            action_type='login',
            module='auth',
            description='管理员登录',
            request=request
        )

        # 生成 Token
        tokens = generate_manager_tokens(manager)

        return Response({
            **tokens,
            'manager': ManagerProfileSerializer(manager).data
        })


class ManagerLogoutView(APIView):
    """管理员登出"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    def post(self, request):
        manager = request.user

        # 记录登出日志
        log_operation(
            manager=manager,
            action_type='logout',
            module='auth',
            description='管理员登出',
            request=request
        )

        return Response({'message': '登出成功'})


class ManagerChangePasswordView(APIView):
    """管理员修改密码"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    def post(self, request):
        serializer = ManagerChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        manager = request.user

        # 验证旧密码
        if not manager.check_password(serializer.validated_data['old_password']):
            return Response(
                {'error': '原密码错误'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 设置新密码
        manager.set_password(serializer.validated_data['new_password'])
        manager.token_version += 1  # 使旧 Token 失效
        manager.save(update_fields=['password', 'token_version'])

        # 记录日志
        log_operation(
            manager=manager,
            action_type='update',
            module='auth',
            description='修改密码',
            request=request
        )

        return Response({'message': '密码修改成功，请重新登录'})


# ══════════════════════════════════════════════════════════════
# 个人信息
# ══════════════════════════════════════════════════════════════

class ManagerProfileView(APIView):
    """管理员个人信息"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    def get(self, request):
        """获取个人信息"""
        manager = request.user
        return Response(ManagerProfileSerializer(manager).data)

    def put(self, request):
        """更新个人信息"""
        manager = request.user
        serializer = ManagerProfileUpdateSerializer(
            manager, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(ManagerProfileSerializer(manager).data)


# ══════════════════════════════════════════════════════════════
# 角色管理
# ══════════════════════════════════════════════════════════════

class ManagerRoleViewSet(viewsets.ModelViewSet):
    """
    管理员角色 CRUD
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    queryset = ManagerRole.objects.all()
    serializer_class = ManagerRoleSerializer
    pagination_class = AdminPagination
    required_module = 'system'  # 供 HasModuleAccess 使用

    def get_queryset(self):
        queryset = super().get_queryset()

        # 搜索
        keyword = self.request.query_params.get('keyword', '')
        if keyword:
            queryset = queryset.filter(name__icontains=keyword)

        # 状态筛选
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        return queryset.order_by('id')

    @action(detail=False, methods=['get'])
    def options(self, request):
        """获取角色选项（用于下拉框）"""
        roles = ManagerRole.objects.filter(is_active=True)
        serializer = ManagerRoleSimpleSerializer(roles, many=True)
        return Response(serializer.data)

    def perform_create(self, serializer):
        role = serializer.save()
        log_operation(
            manager=self.request.user,
            action_type='create',
            module='role',
            description=f'创建角色: {role.name}',
            request=self.request,
            target_type='role',
            target_id=str(role.id)
        )

    def perform_update(self, serializer):
        role = serializer.save()
        log_operation(
            manager=self.request.user,
            action_type='update',
            module='role',
            description=f'更新角色: {role.name}',
            request=self.request,
            target_type='role',
            target_id=str(role.id)
        )

    def perform_destroy(self, instance):
        # 检查是否有管理员使用此角色
        if instance.managers.exists():
            from rest_framework.exceptions import ValidationError
            raise ValidationError('该角色下还有管理员，无法删除')

        log_operation(
            manager=self.request.user,
            action_type='delete',
            module='role',
            description=f'删除角色: {instance.name}',
            request=self.request,
            target_type='role',
            target_id=str(instance.id)
        )
        instance.delete()


# ══════════════════════════════════════════════════════════════
# 管理员管理
# ══════════════════════════════════════════════════════════════

class ManagerViewSet(viewsets.ModelViewSet):
    """
    管理员 CRUD
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    pagination_class = AdminPagination
    required_module = 'system'

    def get_queryset(self):
        queryset = Manager.objects.select_related('role')

        # 搜索
        keyword = self.request.query_params.get('keyword', '')
        if keyword:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(username__icontains=keyword) |
                Q(name__icontains=keyword) |
                Q(phone__icontains=keyword)
            )

        # 角色筛选
        role_id = self.request.query_params.get('role_id')
        if role_id:
            queryset = queryset.filter(role_id=role_id)

        # 状态筛选
        status_param = self.request.query_params.get('status')
        if status_param:
            queryset = queryset.filter(status=status_param)

        return queryset.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return ManagerListSerializer
        elif self.action == 'create':
            return ManagerCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return ManagerUpdateSerializer
        else:
            return ManagerDetailSerializer

    def perform_create(self, serializer):
        manager = serializer.save()
        log_operation(
            manager=self.request.user,
            action_type='create',
            module='manager',
            description=f'创建管理员: {manager.name}({manager.username})',
            request=self.request,
            target_type='manager',
            target_id=str(manager.id)
        )

    def perform_update(self, serializer):
        manager = serializer.save()
        log_operation(
            manager=self.request.user,
            action_type='update',
            module='manager',
            description=f'更新管理员: {manager.name}({manager.username})',
            request=self.request,
            target_type='manager',
            target_id=str(manager.id)
        )

    def perform_destroy(self, instance):
        # 不能删除自己
        if instance.id == self.request.user.id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError('不能删除自己')

        # 不能删除超级管理员
        if instance.is_superuser and not self.request.user.is_superuser:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('无权删除超级管理员')

        log_operation(
            manager=self.request.user,
            action_type='delete',
            module='manager',
            description=f'删除管理员: {instance.name}({instance.username})',
            request=self.request,
            target_type='manager',
            target_id=str(instance.id)
        )
        instance.delete()

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """重置密码"""
        manager = self.get_object()

        # 不能重置超级管理员密码（除非自己是超级管理员）
        if manager.is_superuser and not request.user.is_superuser:
            return Response(
                {'error': '无权重置超级管理员密码'},
                status=status.HTTP_403_FORBIDDEN
            )

        new_password = request.data.get('password', '123456')
        manager.set_password(new_password)
        manager.token_version += 1
        manager.save(update_fields=['password', 'token_version'])

        log_operation(
            manager=request.user,
            action_type='update',
            module='manager',
            description=f'重置管理员密码: {manager.name}({manager.username})',
            request=request,
            target_type='manager',
            target_id=str(manager.id)
        )

        return Response({
            'message': '密码重置成功',
            'password': new_password
        })

    @action(detail=True, methods=['post'])
    def toggle_status(self, request, pk=None):
        """启用/禁用管理员"""
        manager = self.get_object()

        # 不能操作自己
        if manager.id == request.user.id:
            return Response(
                {'error': '不能操作自己'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 不能禁用超级管理员
        if manager.is_superuser and not request.user.is_superuser:
            return Response(
                {'error': '无权操作超级管理员'},
                status=status.HTTP_403_FORBIDDEN
            )

        if manager.status == Manager.Status.ACTIVE:
            manager.status = Manager.Status.DISABLED
            manager.token_version += 1  # 使其 Token 失效
            message = '已禁用'
        else:
            manager.status = Manager.Status.ACTIVE
            message = '已启用'

        manager.save(update_fields=['status', 'token_version'])

        log_operation(
            manager=request.user,
            action_type='update',
            module='manager',
            description=f'{message}管理员: {manager.name}({manager.username})',
            request=request,
            target_type='manager',
            target_id=str(manager.id)
        )

        return Response({
            'message': message,
            'status': manager.status
        })


# ══════════════════════════════════════════════════════════════
# 操作日志
# ══════════════════════════════════════════════════════════════

class ManagerOperationLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    操作日志（只读）
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    pagination_class = AdminPagination
    required_module = 'system'

    def get_queryset(self):
        queryset = ManagerOperationLog.objects.all()

        # 操作人筛选
        manager_id = self.request.query_params.get('manager_id')
        if manager_id:
            queryset = queryset.filter(manager_id=manager_id)

        # 模块筛选
        module = self.request.query_params.get('module')
        if module:
            queryset = queryset.filter(module=module)

        # 操作类型筛选
        action_type = self.request.query_params.get('action')
        if action_type:
            queryset = queryset.filter(action=action_type)

        # 时间范围
        start_time = self.request.query_params.get('start_time')
        end_time = self.request.query_params.get('end_time')
        if start_time:
            queryset = queryset.filter(created_at__gte=start_time)
        if end_time:
            queryset = queryset.filter(created_at__lte=end_time)

        # 关键词搜索
        keyword = self.request.query_params.get('keyword')
        if keyword:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(description__icontains=keyword) |
                Q(manager_name__icontains=keyword)
            )

        return queryset.order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ManagerOperationLogDetailSerializer
        return ManagerOperationLogSerializer


# ══════════════════════════════════════════════════════════════
# 系统配置
# ══════════════════════════════════════════════════════════════

class SystemConfigViewSet(viewsets.ModelViewSet):
    """
    系统配置 CRUD
    """
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    queryset = SystemConfig.objects.all()
    serializer_class = SystemConfigSerializer
    pagination_class = AdminPagination
    required_module = 'system'

    def get_queryset(self):
        queryset = super().get_queryset()

        # 分组筛选
        group = self.request.query_params.get('group')
        if group:
            queryset = queryset.filter(group=group)

        # 关键词搜索
        keyword = self.request.query_params.get('keyword')
        if keyword:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(key__icontains=keyword) |
                Q(description__icontains=keyword)
            )

        return queryset.order_by('group', 'key')

    @action(detail=False, methods=['get'], permission_classes=[AllowAny], authentication_classes=[])
    def public(self, request):
        """获取公开配置"""
        configs = SystemConfig.objects.filter(is_public=True)
        result = {}
        for config in configs:
            result[config.key] = config.get_value()
        return Response(result)

    @action(detail=False, methods=['post'])
    def batch_update(self, request):
        """批量更新配置"""
        serializer = SystemConfigBatchUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        configs = serializer.validated_data['configs']
        updated = []

        for item in configs:
            try:
                config = SystemConfig.objects.get(key=item['key'])
                config.value = str(item['value'])
                config.save(update_fields=['value', 'updated_at'])
                updated.append(item['key'])
            except SystemConfig.DoesNotExist:
                pass

        log_operation(
            manager=request.user,
            action_type='update',
            module='config',
            description=f'批量更新配置: {", ".join(updated)}',
            request=request
        )

        return Response({
            'message': f'成功更新 {len(updated)} 项配置',
            'updated': updated
        })

    @action(detail=False, methods=['get'])
    def groups(self, request):
        """获取所有配置分组"""
        groups = SystemConfig.objects.values_list('group', flat=True).distinct()
        return Response(list(groups))


# ══════════════════════════════════════════════════════════════
# 仪表盘统计
# ══════════════════════════════════════════════════════════════

class DashboardView(APIView):
    """仪表盘统计数据"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    def get(self, request):
        from django.db.models import Count
        from django.utils import timezone

        today = timezone.now().date()

        # 导入商家模型
        try:
            from merchants.models import Merchant, MerchantCategory

            # 商家统计
            merchant_stats = {
                'total': Merchant.objects.count(),
                'active': Merchant.objects.filter(status='active').count(),
                'pending': Merchant.objects.filter(status='pending').count(),
                'today_new': Merchant.objects.filter(created_at__date=today).count(),
            }

            # 分类统计
            category_stats = list(MerchantCategory.objects.annotate(
                merchant_count=Count('merchants')
            ).values('name', 'merchant_count'))
        except ImportError:
            merchant_stats = {}
            category_stats = []

        # 管理员统计
        manager_stats = {
            'total': Manager.objects.count(),
            'active': Manager.objects.filter(status='active').count(),
        }

        # 今日登录
        today_logins = ManagerOperationLog.objects.filter(
            action='login',
            created_at__date=today
        ).count()

        # 最近操作日志
        recent_logs = ManagerOperationLog.objects.order_by('-created_at')[:10]
        recent_logs_data = ManagerOperationLogSerializer(recent_logs, many=True).data

        return Response({
            'merchant_stats': merchant_stats,
            'category_stats': category_stats,
            'manager_stats': manager_stats,
            'today_logins': today_logins,
            'recent_logs': recent_logs_data,
        })