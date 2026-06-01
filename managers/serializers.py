# -*- coding: utf-8 -*-
"""
管理员序列化器
"""

from rest_framework import serializers
from .models import Manager, ManagerRole, ManagerOperationLog, SystemConfig


# ══════════════════════════════════════════════════════════════
# 认证相关
# ══════════════════════════════════════════════════════════════

class ManagerLoginSerializer(serializers.Serializer):
    """登录序列化器"""
    username = serializers.CharField(max_length=50, help_text='用户名')
    password = serializers.CharField(max_length=128, write_only=True, help_text='密码')


class ManagerChangePasswordSerializer(serializers.Serializer):
    """修改密码序列化器"""
    old_password = serializers.CharField(max_length=128, write_only=True, help_text='原密码')
    new_password = serializers.CharField(min_length=6, max_length=128, write_only=True, help_text='新密码')
    confirm_password = serializers.CharField(max_length=128, write_only=True, help_text='确认密码')

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': '两次输入的密码不一致'})
        if attrs['old_password'] == attrs['new_password']:
            raise serializers.ValidationError({'new_password': '新密码不能与原密码相同'})
        return attrs


# ══════════════════════════════════════════════════════════════
# 角色相关
# ══════════════════════════════════════════════════════════════

class ManagerRoleSerializer(serializers.ModelSerializer):
    """角色序列化器（完整）"""
    manager_count = serializers.SerializerMethodField(help_text='使用该角色的管理员数量')

    class Meta:
        model = ManagerRole
        fields = [
            'id', 'name', 'code', 'permissions', 'modules',
            'description', 'is_active', 'manager_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'manager_count']

    def get_manager_count(self, obj):
        return obj.managers.count()

    def validate_code(self, value):
        """验证角色代码唯一性"""
        instance = self.instance
        if ManagerRole.objects.filter(code=value).exclude(pk=instance.pk if instance else None).exists():
            raise serializers.ValidationError('角色代码已存在')
        return value


class ManagerRoleSimpleSerializer(serializers.ModelSerializer):
    """角色简单序列化器（用于下拉框）"""

    class Meta:
        model = ManagerRole
        fields = ['id', 'name', 'code']


# ══════════════════════════════════════════════════════════════
# 管理员相关
# ══════════════════════════════════════════════════════════════

class ManagerListSerializer(serializers.ModelSerializer):
    """管理员列表序列化器"""
    role_name = serializers.CharField(source='role.name', read_only=True, default='')
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Manager
        fields = [
            'id', 'username', 'name', 'phone', 'email', 'avatar',
            'role', 'role_name', 'role_code', 'is_superuser',
            'status', 'status_display', 'last_login', 'last_login_ip',
            'created_at'
        ]


class ManagerDetailSerializer(serializers.ModelSerializer):
    """管理员详情序列化器"""
    role_info = ManagerRoleSimpleSerializer(source='role', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    permissions = serializers.SerializerMethodField()
    modules = serializers.SerializerMethodField()

    class Meta:
        model = Manager
        fields = [
            'id', 'username', 'name', 'phone', 'email', 'avatar',
            'role', 'role_info', 'role_code', 'is_superuser',
            'status', 'status_display', 'permissions', 'modules',
            'last_login', 'last_login_ip', 'created_at', 'updated_at'
        ]

    def get_permissions(self, obj):
        return obj.get_permissions()

    def get_modules(self, obj):
        return obj.get_modules()


class ManagerCreateSerializer(serializers.ModelSerializer):
    """创建管理员序列化器"""
    password = serializers.CharField(
        min_length=6, max_length=128, write_only=True,
        help_text='密码，最少6位'
    )
    confirm_password = serializers.CharField(
        max_length=128, write_only=True,
        help_text='确认密码'
    )

    class Meta:
        model = Manager
        fields = [
            'username', 'password', 'confirm_password',
            'name', 'phone', 'email', 'avatar',
            'role', 'role_code', 'is_superuser', 'status'
        ]

    def validate_username(self, value):
        if Manager.objects.filter(username=value).exists():
            raise serializers.ValidationError('用户名已存在')
        return value

    def validate(self, attrs):
        if attrs.get('password') != attrs.get('confirm_password'):
            raise serializers.ValidationError({'confirm_password': '两次输入的密码不一致'})
        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password', None)
        password = validated_data.pop('password')
        manager = Manager(**validated_data)
        manager.set_password(password)
        manager.save()
        return manager


class ManagerUpdateSerializer(serializers.ModelSerializer):
    """更新管理员序列化器"""

    class Meta:
        model = Manager
        fields = [
            'name', 'phone', 'email', 'avatar',
            'role', 'role_code', 'is_superuser', 'status'
        ]

    def validate(self, attrs):
        # 不能将自己设置为非超级管理员（如果原来是）
        request = self.context.get('request')
        if request and self.instance:
            if self.instance.id == request.user.id:
                if 'is_superuser' in attrs and not attrs['is_superuser'] and self.instance.is_superuser:
                    raise serializers.ValidationError({'is_superuser': '不能取消自己的超级管理员权限'})
                if 'status' in attrs and attrs['status'] != Manager.Status.ACTIVE:
                    raise serializers.ValidationError({'status': '不能禁用自己'})
        return attrs


class ManagerProfileSerializer(serializers.ModelSerializer):
    """个人信息序列化器"""
    role_info = ManagerRoleSimpleSerializer(source='role', read_only=True)
    permissions = serializers.SerializerMethodField()
    modules = serializers.SerializerMethodField()

    class Meta:
        model = Manager
        fields = [
            'id', 'username', 'name', 'phone', 'email', 'avatar',
            'role', 'role_info', 'role_code', 'is_superuser',
            'permissions', 'modules', 'last_login', 'created_at'
        ]

    def get_permissions(self, obj):
        return obj.get_permissions()

    def get_modules(self, obj):
        return obj.get_modules()


class ManagerProfileUpdateSerializer(serializers.ModelSerializer):
    """更新个人信息序列化器"""

    class Meta:
        model = Manager
        fields = ['name', 'phone', 'email', 'avatar']


# ══════════════════════════════════════════════════════════════
# 操作日志相关
# ══════════════════════════════════════════════════════════════

class ManagerOperationLogSerializer(serializers.ModelSerializer):
    """操作日志列表序列化器"""
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = ManagerOperationLog
        fields = [
            'id', 'manager_name', 'manager_username',
            'action', 'action_display', 'module', 'description',
            'target_type', 'target_id', 'ip_address',
            'created_at'
        ]


class ManagerOperationLogDetailSerializer(serializers.ModelSerializer):
    """操作日志详情序列化器"""
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = ManagerOperationLog
        fields = [
            'id', 'manager', 'manager_name', 'manager_username',
            'action', 'action_display', 'module', 'description',
            'target_type', 'target_id',
            'request_data', 'response_data', 'old_data', 'new_data',
            'ip_address', 'user_agent', 'request_id', 'duration_ms',
            'created_at'
        ]


# ══════════════════════════════════════════════════════════════
# 系统配置相关
# ══════════════════════════════════════════════════════════════

class SystemConfigSerializer(serializers.ModelSerializer):
    """系统配置序列化器"""
    typed_value = serializers.SerializerMethodField(help_text='类型转换后的值')

    class Meta:
        model = SystemConfig
        fields = [
            'id', 'key', 'value', 'typed_value', 'value_type',
            'group', 'description', 'is_public',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'typed_value']

    def get_typed_value(self, obj):
        return obj.get_value()

    def validate_key(self, value):
        """验证配置键唯一性"""
        instance = self.instance
        if SystemConfig.objects.filter(key=value).exclude(pk=instance.pk if instance else None).exists():
            raise serializers.ValidationError('配置键已存在')
        return value


class SystemConfigUpdateSerializer(serializers.ModelSerializer):
    """系统配置更新序列化器"""

    class Meta:
        model = SystemConfig
        fields = ['value', 'description', 'is_public']


class SystemConfigBatchUpdateSerializer(serializers.Serializer):
    """批量更新配置序列化器"""

    class ConfigItemSerializer(serializers.Serializer):
        key = serializers.CharField(max_length=100)
        value = serializers.CharField()

    configs = ConfigItemSerializer(many=True)

    def validate_configs(self, value):
        if not value:
            raise serializers.ValidationError('配置列表不能为空')
        return value