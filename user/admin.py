from django.contrib import admin

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import User, UserAddress, SuperAdmin


class UserAddressInline(admin.TabularInline):
    """用户地址内联编辑"""
    model = UserAddress
    extra = 0
    fields = ('receiver_name', 'receiver_phone', 'province', 'city', 'district',
              'detail_address', 'is_default', 'tag')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """用户管理"""

    list_display = (
        'id', 'display_name_admin', 'phone', 'email', 'gender_display',
        'is_vip_display', 'is_verified_display', 'level', 'followers_count',
        'is_active', 'created_at'
    )

    list_filter = (
        'is_active', 'is_vip', 'is_verified', 'gender', 'vip_level',
        'verification_type', 'is_public', 'created_at', 'last_active_at'
    )

    search_fields = (
        'username', 'phone', 'email', 'bio', 'openid', 'unionid'
    )

    readonly_fields = (
        'created_at', 'updated_at', 'last_login', 'last_active_at',
        'followers_count', 'following_count', 'posts_count', 'likes_received'
    )

    fieldsets = (
        ('基础信息', {
            'fields': ('username', 'avatar', 'bio', 'phone', 'email')
        }),
        ('个人信息', {
            'fields': ('gender', 'birth_date'),
            'classes': ('collapse',)
        }),
        ('微信信息', {
            'fields': ('openid', 'unionid'),
            'classes': ('collapse',)
        }),
        ('VIP信息', {
            'fields': ('is_vip', 'vip_level', 'vip_expired_at'),
            'classes': ('collapse',)
        }),
        ('社交统计', {
            'fields': ('followers_count', 'following_count', 'posts_count', 'likes_received'),
            'classes': ('collapse',)
        }),
        ('认证信息', {
            'fields': ('is_verified', 'verification_type', 'verified_at'),
            'classes': ('collapse',)
        }),
        ('等级积分', {
            'fields': ('level', 'exp', 'integral', 'gold'),
            'classes': ('collapse',)
        }),
        ('隐私设置', {
            'fields': ('is_public', 'allow_message'),
            'classes': ('collapse',)
        }),
        ('状态信息', {
            'fields': ('is_active', 'last_login', 'last_active_at'),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    inlines = [UserAddressInline]

    list_per_page = 50
    date_hierarchy = 'created_at'

    actions = ['make_active', 'make_inactive', 'make_vip', 'cancel_vip']

    def display_name_admin(self, obj):
        """显示用户名"""
        if obj.avatar:
            return format_html(
                '<img src="{}" width="30" height="30" style="border-radius: 50%; margin-right: 10px;"/>'
                '<strong>{}</strong>',
                obj.avatar, obj.display_name
            )
        return obj.display_name

    display_name_admin.short_description = '用户'
    display_name_admin.admin_order_field = 'username'

    def gender_display(self, obj):
        """性别显示"""
        gender_dict = dict(User.GENDER_CHOICES)
        return gender_dict.get(obj.gender, '未设置')

    gender_display.short_description = '性别'
    gender_display.admin_order_field = 'gender'

    def is_vip_display(self, obj):
        """VIP状态显示"""
        if obj.is_vip:
            return format_html(
                '<span style="color: #ffa500;">VIP{}</span>',
                obj.vip_level
            )
        return '普通用户'

    is_vip_display.short_description = 'VIP状态'
    is_vip_display.admin_order_field = 'is_vip'

    def is_verified_display(self, obj):
        """认证状态显示"""
        if obj.is_verified:
            return format_html(
                '<span style="color: #28a745;">✓ {}</span>',
                obj.verification_type or '已认证'
            )
        return format_html('<span style="color: #dc3545;">未认证</span>')

    is_verified_display.short_description = '认证状态'
    is_verified_display.admin_order_field = 'is_verified'

    def make_active(self, request, queryset):
        """批量激活用户"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'成功激活了 {updated} 个用户')

    make_active.short_description = '激活选中用户'

    def make_inactive(self, request, queryset):
        """批量禁用用户"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'成功禁用了 {updated} 个用户')

    make_inactive.short_description = '禁用选中用户'

    def make_vip(self, request, queryset):
        """批量设为VIP"""
        updated = queryset.update(is_vip=True, vip_level=1)
        self.message_user(request, f'成功将 {updated} 个用户设为VIP')

    make_vip.short_description = '设为VIP用户'

    def cancel_vip(self, request, queryset):
        """批量取消VIP"""
        updated = queryset.update(is_vip=False, vip_level=0)
        self.message_user(request, f'成功取消了 {updated} 个用户的VIP')

    cancel_vip.short_description = '取消VIP用户'


@admin.register(UserAddress)
class UserAddressAdmin(admin.ModelAdmin):
    """用户地址管理"""

    list_display = (
        'id', 'user_link', 'receiver_name', 'receiver_phone',
        'address_display', 'is_default', 'tag', 'created_at'
    )

    list_filter = (
        'is_default', 'province', 'city', 'tag', 'created_at'
    )

    search_fields = (
        'receiver_name', 'receiver_phone', 'detail_address',
        'user__username', 'user__phone'
    )

    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        ('基础信息', {
            'fields': ('user', 'receiver_name', 'receiver_phone')
        }),
        ('地址信息', {
            'fields': ('province', 'city', 'district', 'detail_address', 'tag')
        }),
        ('位置信息', {
            'fields': ('longitude', 'latitude', 'access_instructions'),
            'classes': ('collapse',)
        }),
        ('设置', {
            'fields': ('is_default',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    list_per_page = 50
    date_hierarchy = 'created_at'

    def user_link(self, obj):
        """用户链接"""
        url = reverse('admin:user_user_change', args=[obj.user.id])  # 请替换 your_app 为实际应用名
        return format_html('<a href="{}">{}</a>', url, obj.user.display_name)

    user_link.short_description = '用户'
    user_link.admin_order_field = 'user__username'

    def address_display(self, obj):
        """地址显示"""
        address_parts = []
        if obj.province:
            address_parts.append(obj.province)
        if obj.city:
            address_parts.append(obj.city)
        if obj.district:
            address_parts.append(obj.district)
        address_parts.append(obj.detail_address)
        return ''.join(address_parts)

    address_display.short_description = '地址'


@admin.register(SuperAdmin)
class SuperAdminAdmin(admin.ModelAdmin):
    """超级管理员管理"""

    list_display = (
        'id', 'username', 'phone', 'is_active', 'last_login', 'created_at'
    )

    list_filter = (
        'is_active', 'created_at', 'last_login'
    )

    search_fields = (
        'username', 'phone'
    )

    readonly_fields = (
        'created_at', 'updated_at', 'last_login'
    )

    fieldsets = (
        ('基础信息', {
            'fields': ('username', 'phone')
        }),
        ('密码', {
            'fields': ('password',),
            'description': '密码将自动加密存储'
        }),
        ('状态', {
            'fields': ('is_active',)
        }),
        ('时间信息', {
            'fields': ('last_login', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    list_per_page = 30
    date_hierarchy = 'created_at'

    def save_model(self, request, obj, form, change):
        """保存模型时处理密码"""
        if 'password' in form.changed_data:
            obj.set_password(form.cleaned_data['password'])
        super().save_model(request, obj, form, change)


# 自定义管理后台标题
admin.site.site_header = '用户管理系统'
admin.site.site_title = '用户管理系统'
admin.site.index_title = '欢迎使用用户管理系统'
