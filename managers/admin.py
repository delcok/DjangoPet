# -*- coding: utf-8 -*-
"""
管理员模块 Django Admin 配置
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django import forms
from .models import Manager, ManagerRole, ManagerOperationLog, SystemConfig


# ══════════════════════════════════════════════════════════════
# 角色管理
# ══════════════════════════════════════════════════════════════

@admin.register(ManagerRole)
class ManagerRoleAdmin(admin.ModelAdmin):
    """角色管理"""

    list_display = [
        'id', 'name', 'code', 'permissions_preview', 'modules_preview',
        'is_active', 'manager_count', 'created_at'
    ]
    list_display_links = ['id', 'name']
    list_editable = ['is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code', 'description']
    ordering = ['id']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'code', 'description')
        }),
        ('权限配置', {
            'fields': ('permissions', 'modules'),
            'description': mark_safe('''
                <p><strong>权限格式：</strong>["merchant:view", "merchant:edit", "order:view", "*"]</p>
                <p><strong>模块格式：</strong>["merchant", "order", "product", "user", "system", "*"]</p>
                <p><strong>通配符 * 表示所有权限/模块</strong></p>
            ''')
        }),
        ('状态', {
            'fields': ('is_active',)
        }),
    )

    def permissions_preview(self, obj):
        """权限预览"""
        if not obj.permissions:
            return '-'
        if '*' in obj.permissions:
            # Django 6.0+: 没有格式化参数时使用 mark_safe
            return mark_safe('<span style="color:#52c41a;font-weight:bold;">全部权限</span>')
        count = len(obj.permissions)
        preview = ', '.join(obj.permissions[:3])
        if count > 3:
            preview += f' 等{count}项'
        return preview

    permissions_preview.short_description = '权限'

    def modules_preview(self, obj):
        """模块预览"""
        if not obj.modules:
            return '-'
        if '*' in obj.modules:
            return mark_safe('<span style="color:#52c41a;font-weight:bold;">全部模块</span>')
        return ', '.join(obj.modules)

    modules_preview.short_description = '可访问模块'

    def manager_count(self, obj):
        """管理员数量"""
        count = obj.managers.count()
        active_count = obj.managers.filter(status='active').count()
        if count == 0:
            return '0'
        return format_html(
            '<span title="活跃/总数">{} / {}</span>',
            active_count, count
        )

    manager_count.short_description = '管理员数'


# ══════════════════════════════════════════════════════════════
# 管理员表单（支持密码设置）
# ══════════════════════════════════════════════════════════════

class ManagerAdminForm(forms.ModelForm):
    """管理员表单 - 支持密码设置"""

    new_password = forms.CharField(
        label='设置密码',
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='留空则不修改密码。新建管理员时如不填写，默认密码为 123456'
    )
    confirm_password = forms.CharField(
        label='确认密码',
        required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        help_text='再次输入密码以确认'
    )

    class Meta:
        model = Manager
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')

        if new_password or confirm_password:
            if new_password != confirm_password:
                raise forms.ValidationError({'confirm_password': '两次输入的密码不一致'})
            if len(new_password) < 6:
                raise forms.ValidationError({'new_password': '密码长度至少为6位'})

        return cleaned_data


# ══════════════════════════════════════════════════════════════
# 管理员管理
# ══════════════════════════════════════════════════════════════

@admin.register(Manager)
class ManagerAdmin(admin.ModelAdmin):
    """管理员管理"""

    form = ManagerAdminForm

    list_display = [
        'id', 'username', 'name', 'phone_display', 'role_display',
        'is_superuser_icon', 'status_badge', 'last_login', 'created_at'
    ]
    list_display_links = ['id', 'username']
    list_filter = ['status', 'is_superuser', 'role', 'role_code', 'created_at']
    search_fields = ['username', 'name', 'phone', 'email']
    raw_id_fields = ['role']
    readonly_fields = [
        'token_version', 'login_fail_count', 'locked_until',
        'last_login', 'last_login_ip', 'created_at', 'updated_at'
    ]
    ordering = ['-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('username', 'name', 'phone', 'email', 'avatar')
        }),
        ('密码设置', {
            'fields': ('new_password', 'confirm_password'),
            'description': '设置或重置管理员密码'
        }),
        ('角色与权限', {
            'fields': ('role', 'role_code', 'is_superuser'),
            'description': '优先使用 role 关联角色，role_code 用于向下兼容'
        }),
        ('状态与安全', {
            'fields': ('status', 'login_fail_count', 'locked_until', 'token_version')
        }),
        ('登录信息', {
            'fields': ('last_login', 'last_login_ip'),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def phone_display(self, obj):
        """手机号脱敏显示"""
        if obj.phone and len(obj.phone) >= 7:
            return format_html(
                '{}****{}',
                obj.phone[:3], obj.phone[-4:]
            )
        return obj.phone or '-'

    phone_display.short_description = '手机号'

    def role_display(self, obj):
        """角色显示"""
        if obj.role:
            return format_html(
                '<span style="color:#1890ff;">{}</span>',
                obj.role.name
            )
        elif obj.role_code:
            return format_html(
                '<span style="color:#8c8c8c;">{}</span>',
                obj.get_role_code_display()
            )
        return '-'

    role_display.short_description = '角色'

    def is_superuser_icon(self, obj):
        """超级管理员图标"""
        if obj.is_superuser:
            # Django 6.0+: 没有格式化参数时使用 mark_safe
            return mark_safe(
                '<span style="color:#faad14;font-size:16px;" title="超级管理员">★</span>'
            )
        return ''

    is_superuser_icon.short_description = '超管'

    def status_badge(self, obj):
        """状态徽章"""
        colors = {
            'active': '#52c41a',
            'disabled': '#ff4d4f',
        }
        color = colors.get(obj.status, '#8c8c8c')
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>',
            color, obj.get_status_display()
        )

    status_badge.short_description = '状态'

    # ══════ 批量操作 ══════
    actions = ['enable_managers', 'disable_managers', 'reset_password_action']

    @admin.action(description='✅ 启用选中的管理员')
    def enable_managers(self, request, queryset):
        count = queryset.exclude(pk=request.user.pk if hasattr(request.user, 'pk') else None).update(status='active')
        self.message_user(request, f'已启用 {count} 个管理员')

    @admin.action(description='🚫 禁用选中的管理员')
    def disable_managers(self, request, queryset):
        # 排除超级管理员和自己
        count = queryset.filter(is_superuser=False).exclude(
            pk=request.user.pk if hasattr(request.user, 'pk') else None
        ).update(status='disabled')
        self.message_user(request, f'已禁用 {count} 个管理员（超级管理员和自己已排除）')

    @admin.action(description='🔑 重置密码为 123456')
    def reset_password_action(self, request, queryset):
        from django.contrib.auth.hashers import make_password
        count = 0
        for manager in queryset:
            manager.password = make_password('123456')
            manager.token_version += 1
            manager.save(update_fields=['password', 'token_version'])
            count += 1
        self.message_user(request, f'已重置 {count} 个管理员的密码为 123456')

    def save_model(self, request, obj, form, change):
        """保存时处理密码"""
        new_password = form.cleaned_data.get('new_password')

        if new_password:
            # 如果填写了新密码，使用新密码
            obj.set_password(new_password)
            if change:
                obj.token_version += 1  # 修改密码时使旧 Token 失效
        elif not change:
            # 新建时如果没有密码，设置默认密码
            if not obj.password or not obj.password.startswith('pbkdf2_'):
                obj.set_password('123456')

        super().save_model(request, obj, form, change)


# ══════════════════════════════════════════════════════════════
# 操作日志
# ══════════════════════════════════════════════════════════════

@admin.register(ManagerOperationLog)
class ManagerOperationLogAdmin(admin.ModelAdmin):
    """操作日志管理"""

    list_display = [
        'id', 'manager_info', 'action_badge', 'module',
        'description_short', 'target_info', 'ip_address', 'created_at'
    ]
    list_display_links = ['id']
    list_filter = ['action', 'module', 'created_at']
    search_fields = ['manager_name', 'manager_username', 'description', 'ip_address', 'target_id']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    readonly_fields = [
        'manager', 'manager_name', 'manager_username',
        'action', 'module', 'description',
        'target_type', 'target_id',
        'request_data', 'response_data', 'old_data', 'new_data',
        'ip_address', 'user_agent', 'request_id', 'duration_ms',
        'created_at'
    ]

    fieldsets = (
        ('操作人信息', {
            'fields': ('manager', 'manager_name', 'manager_username')
        }),
        ('操作信息', {
            'fields': ('action', 'module', 'description')
        }),
        ('目标信息', {
            'fields': ('target_type', 'target_id')
        }),
        ('请求详情', {
            'fields': ('request_data', 'response_data'),
            'classes': ('collapse',)
        }),
        ('数据变更', {
            'fields': ('old_data', 'new_data'),
            'classes': ('collapse',)
        }),
        ('请求来源', {
            'fields': ('ip_address', 'user_agent', 'request_id', 'duration_ms')
        }),
        ('时间', {
            'fields': ('created_at',)
        }),
    )

    def manager_info(self, obj):
        """操作人信息"""
        return format_html(
            '<span title="{}">{}</span>',
            obj.manager_username or '', obj.manager_name or ''
        )

    manager_info.short_description = '操作人'

    def action_badge(self, obj):
        """操作类型徽章"""
        colors = {
            'create': '#52c41a',
            'update': '#1890ff',
            'delete': '#ff4d4f',
            'login': '#722ed1',
            'logout': '#8c8c8c',
            'export': '#13c2c2',
            'import': '#eb2f96',
            'audit': '#faad14',
            'other': '#8c8c8c',
        }
        color = colors.get(obj.action, '#8c8c8c')
        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            color, obj.get_action_display()
        )

    action_badge.short_description = '操作'

    def description_short(self, obj):
        """描述截断"""
        desc = obj.description or ''
        if len(desc) > 40:
            return format_html(
                '<span title="{}">{}</span>',
                desc, desc[:40] + '...'
            )
        return desc

    description_short.short_description = '描述'

    def target_info(self, obj):
        """目标信息"""
        if obj.target_type and obj.target_id:
            return format_html(
                '<code>{}:{}</code>',
                obj.target_type, obj.target_id
            )
        return '-'

    target_info.short_description = '目标'

    # 禁止添加和修改
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # 只有超级用户可以删除日志
        return request.user.is_superuser


# ══════════════════════════════════════════════════════════════
# 系统配置
# ══════════════════════════════════════════════════════════════

@admin.register(SystemConfig)
class SystemConfigAdmin(admin.ModelAdmin):
    """系统配置管理"""

    list_display = [
        'id', 'key', 'value_preview', 'value_type_badge',
        'group', 'is_public', 'description_short', 'updated_at'
    ]
    list_display_links = ['id', 'key']
    list_editable = ['is_public']
    list_filter = ['group', 'value_type', 'is_public', 'updated_at']
    search_fields = ['key', 'value', 'description']
    ordering = ['group', 'key']

    fieldsets = (
        ('配置信息', {
            'fields': ('key', 'value', 'value_type')
        }),
        ('分组与描述', {
            'fields': ('group', 'description')
        }),
        ('访问控制', {
            'fields': ('is_public',),
            'description': '公开配置可被前端直接获取，无需登录'
        }),
    )

    def value_preview(self, obj):
        """值预览"""
        value = obj.value or ''
        if len(value) > 50:
            return format_html(
                '<span title="{}">{}</span>',
                value[:200], value[:50] + '...'
            )
        return value

    value_preview.short_description = '配置值'

    def value_type_badge(self, obj):
        """值类型徽章"""
        colors = {
            'string': '#1890ff',
            'number': '#52c41a',
            'boolean': '#722ed1',
            'json': '#faad14',
        }
        color = colors.get(obj.value_type, '#8c8c8c')
        return format_html(
            '<span style="color:{};border:1px solid {};padding:2px 6px;border-radius:3px;font-size:11px;">{}</span>',
            color, color, obj.get_value_type_display()
        )

    value_type_badge.short_description = '类型'

    def description_short(self, obj):
        """描述截断"""
        if not obj.description:
            return '-'
        if len(obj.description) > 30:
            return obj.description[:30] + '...'
        return obj.description

    description_short.short_description = '描述'

    # ══════ 批量操作 ══════
    actions = ['make_public', 'make_private']

    @admin.action(description='🌐 设为公开')
    def make_public(self, request, queryset):
        count = queryset.update(is_public=True)
        self.message_user(request, f'已将 {count} 项配置设为公开')

    @admin.action(description='🔒 设为私有')
    def make_private(self, request, queryset):
        count = queryset.update(is_public=False)
        self.message_user(request, f'已将 {count} 项配置设为私有')


# ══════════════════════════════════════════════════════════════
# Admin 站点配置
# ══════════════════════════════════════════════════════════════

admin.site.site_header = '社区私域服务 - 管理后台'
admin.site.site_title = '社区私域服务'
admin.site.index_title = '欢迎使用管理后台'