# managers/models.py
"""
管理员模型
包含：管理员、角色、操作日志、系统配置
"""

from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.core.serializers.json import DjangoJSONEncoder


class ManagerRole(models.Model):
    """管理员角色"""

    name = models.CharField(max_length=50, unique=True, verbose_name='角色名称')
    code = models.CharField(max_length=50, unique=True, verbose_name='角色代码')
    permissions = models.JSONField(
        default=list, blank=True, verbose_name='权限列表',
        help_text='如 ["merchant:view", "merchant:edit", "order:view"]'
    )
    modules = models.JSONField(
        default=list, blank=True, verbose_name='可访问模块',
        help_text='如 ["merchant", "order", "product", "user"]'
    )
    description = models.CharField(max_length=200, blank=True, default='', verbose_name='角色描述')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'manager_role'
        verbose_name = '管理员角色'
        verbose_name_plural = verbose_name
        ordering = ['id']

    def __str__(self):
        return self.name

    def has_permission(self, permission: str) -> bool:
        """检查是否有某个权限"""
        if '*' in self.permissions:
            return True
        return permission in self.permissions

    def has_module_access(self, module: str) -> bool:
        """检查是否有某个模块的访问权限"""
        if '*' in self.modules:
            return True
        return module in self.modules


class Manager(models.Model):
    """管理员"""

    class Status(models.TextChoices):
        ACTIVE = 'active', '正常'
        DISABLED = 'disabled', '已禁用'

    class Role(models.TextChoices):
        """预定义角色（向下兼容）"""
        SUPER_ADMIN = 'super_admin', '超级管理员'
        ADMIN = 'admin', '管理员'
        OPERATOR = 'operator', '运营'
        CUSTOMER_SERVICE = 'customer_service', '客服'
        FINANCE = 'finance', '财务'

    # ══════ 基础信息 ══════
    username = models.CharField(
        max_length=50, unique=True, db_index=True,
        verbose_name='用户名'
    )
    password = models.CharField(max_length=128, verbose_name='密码')
    name = models.CharField(max_length=50, verbose_name='姓名')
    phone = models.CharField(
        max_length=17, blank=True, default='',
        verbose_name='手机号'
    )
    email = models.EmailField(blank=True, default='', verbose_name='邮箱')
    avatar = models.CharField(max_length=255, blank=True, default='', verbose_name='头像')

    # ══════ 角色与权限 ══════
    role = models.ForeignKey(
        ManagerRole, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='managers', verbose_name='角色'
    )
    # 向下兼容的角色字段
    role_code = models.CharField(
        max_length=30, choices=Role.choices,
        default=Role.OPERATOR, db_index=True,
        verbose_name='角色代码'
    )
    is_superuser = models.BooleanField(
        default=False, verbose_name='是否超级管理员',
        help_text='超级管理员拥有所有权限'
    )

    # ══════ 状态与安全 ══════
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.ACTIVE, db_index=True,
        verbose_name='状态'
    )
    login_fail_count = models.PositiveSmallIntegerField(
        default=0, verbose_name='连续登录失败次数'
    )
    locked_until = models.DateTimeField(
        null=True, blank=True, verbose_name='锁定截止时间'
    )
    token_version = models.PositiveIntegerField(
        default=1, verbose_name='Token版本',
        help_text='修改密码或强制下线时递增'
    )
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='最后登录时间')
    last_login_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name='最后登录IP')

    # ══════ 时间戳 ══════
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'manager'
        verbose_name = '管理员'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name}({self.username})"

    def set_password(self, raw_password: str):
        """设置密码"""
        self.password = make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        """验证密码"""
        return check_password(raw_password, self.password)

    @property
    def is_active(self) -> bool:
        """是否可用"""
        return self.status == self.Status.ACTIVE

    @property
    def is_super_admin(self) -> bool:
        """是否是超级管理员（兼容 permissions.py）"""
        return self.is_superuser or self.role_code == self.Role.SUPER_ADMIN

    def has_permission(self, permission: str) -> bool:
        """检查是否有某个权限"""
        if self.is_superuser:
            return True
        if self.role:
            return self.role.has_permission(permission)
        return False

    def has_module_access(self, module: str) -> bool:
        """检查是否有某个模块的访问权限（供 HasModuleAccess 权限类使用）"""
        if self.is_superuser:
            return True
        if self.role:
            return self.role.has_module_access(module)
        return False

    def get_permissions(self) -> list:
        """获取所有权限"""
        if self.is_superuser:
            return ['*']
        if self.role:
            return self.role.permissions
        return []

    def get_modules(self) -> list:
        """获取所有可访问模块"""
        if self.is_superuser:
            return ['*']
        if self.role:
            return self.role.modules
        return []

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False


class ManagerOperationLog(models.Model):
    """管理员操作日志"""

    class ActionType(models.TextChoices):
        CREATE = 'create', '创建'
        UPDATE = 'update', '更新'
        DELETE = 'delete', '删除'
        LOGIN = 'login', '登录'
        LOGOUT = 'logout', '登出'
        EXPORT = 'export', '导出'
        IMPORT = 'import', '导入'
        AUDIT = 'audit', '审核'
        OTHER = 'other', '其他'

    # ══════ 操作人信息（冗余存储，防止删除后丢失）══════
    manager = models.ForeignKey(
        Manager, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='operation_logs',
        verbose_name='操作人'
    )
    manager_name = models.CharField(max_length=50, verbose_name='操作人姓名')
    manager_username = models.CharField(max_length=50, verbose_name='操作人用户名')

    # ══════ 操作信息 ══════
    action = models.CharField(
        max_length=20, choices=ActionType.choices,
        default=ActionType.OTHER, db_index=True,
        verbose_name='操作类型'
    )
    module = models.CharField(max_length=50, db_index=True, verbose_name='操作模块')
    description = models.CharField(max_length=500, verbose_name='操作描述')

    # ══════ 目标信息 ══════
    target_type = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='目标类型',
        help_text='如 merchant, order, product'
    )
    target_id = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='目标ID'
    )

    # ══════ 详情 ══════
    request_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder, verbose_name='请求数据')
    response_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder, verbose_name='响应数据')
    old_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder, verbose_name='变更前数据')
    new_data = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder, verbose_name='变更后数据')

    # ══════ 请求信息 ══════
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='IP地址')
    user_agent = models.CharField(max_length=500, blank=True, default='', verbose_name='User-Agent')
    request_id = models.CharField(max_length=36, blank=True, default='', verbose_name='请求ID')
    duration_ms = models.PositiveIntegerField(null=True, blank=True, verbose_name='耗时(ms)')

    # ══════ 时间 ══════
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='操作时间')

    class Meta:
        db_table = 'manager_operation_log'
        verbose_name = '操作日志'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['manager', '-created_at']),
            models.Index(fields=['module', 'action', '-created_at']),
            models.Index(fields=['target_type', 'target_id']),
        ]

    def __str__(self):
        return f"{self.manager_name} - {self.description}"


class SystemConfig(models.Model):
    """系统配置"""

    class ValueType(models.TextChoices):
        STRING = 'string', '字符串'
        NUMBER = 'number', '数字'
        BOOLEAN = 'boolean', '布尔值'
        JSON = 'json', 'JSON'

    key = models.CharField(max_length=100, unique=True, verbose_name='配置键')
    value = models.TextField(verbose_name='配置值')
    value_type = models.CharField(
        max_length=20, choices=ValueType.choices,
        default=ValueType.STRING, verbose_name='值类型'
    )
    group = models.CharField(
        max_length=50, blank=True, default='default',
        db_index=True, verbose_name='配置分组'
    )
    description = models.CharField(max_length=200, blank=True, default='', verbose_name='配置描述')
    is_public = models.BooleanField(
        default=False, verbose_name='是否公开',
        help_text='公开配置可被前端直接获取'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'system_config'
        verbose_name = '系统配置'
        verbose_name_plural = verbose_name
        ordering = ['group', 'key']

    def __str__(self):
        return f"{self.group}.{self.key}"

    def get_value(self):
        """获取类型转换后的值"""
        import json

        if self.value_type == self.ValueType.NUMBER:
            try:
                return int(self.value) if '.' not in self.value else float(self.value)
            except ValueError:
                return 0
        elif self.value_type == self.ValueType.BOOLEAN:
            return self.value.lower() in ('true', '1', 'yes')
        elif self.value_type == self.ValueType.JSON:
            try:
                return json.loads(self.value)
            except json.JSONDecodeError:
                return {}
        return self.value

    @classmethod
    def get(cls, key: str, default=None):
        """获取配置值"""
        try:
            config = cls.objects.get(key=key)
            return config.get_value()
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key: str, value, value_type: str = 'string', group: str = 'default', description: str = ''):
        """设置配置值"""
        import json

        if value_type == 'json' and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        elif value_type == 'boolean':
            value = 'true' if value else 'false'
        else:
            value = str(value)

        config, created = cls.objects.update_or_create(
            key=key,
            defaults={
                'value': value,
                'value_type': value_type,
                'group': group,
                'description': description
            }
        )
        return config