from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils import timezone
from .models import User, UserAuthProvider, UserDevice, UserLoginLog


class UserAuthProviderInline(admin.TabularInline):
    model = UserAuthProvider
    extra = 0
    readonly_fields = ('provider', 'provider_uid', 'union_id', 'created_at')
    fields = ('provider', 'provider_uid', 'union_id', 'created_at')
    can_delete = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'avatar_tag', 'display_name', 'phone_masked',
        'gender', 'vip_tag', 'is_verified', 'level',
        'social_tag',                       # ★ 宠物端社交概要
        'status_tag', 'register_channel', 'created_at'
    )

    list_filter = (
        'is_active', 'is_banned', 'is_vip', 'is_verified',
        'gender', 'register_channel', 'created_at'
    )

    search_fields = ('id', 'username', 'phone', 'email')

    readonly_fields = (
        'id', 'created_at', 'updated_at', 'last_login',
        'last_active_at', 'verified_at',
        # ★ 社交统计系统维护，不允许后台手改
        'followers_count', 'following_count', 'posts_count', 'likes_received',
    )

    fieldsets = (
        ('基础信息', {
            'fields': ('id', 'username', 'avatar', 'bio', 'phone', 'email')
        }),
        ('个人信息', {
            'fields': ('gender', 'birth_date'),
        }),
        ('VIP', {
            'fields': ('is_vip', 'vip_level', 'vip_expired_at'),
        }),
        ('等级 & 社交', {                    # ★ 社交统计只读展示
            'fields': (
                'level', 'exp',
                'followers_count', 'following_count', 'posts_count', 'likes_received',
            ),
            'classes': ('collapse',)
        }),
        ('状态', {
            'fields': ('is_active', 'is_banned', 'ban_reason'),
        }),
        ('时间', {
            'fields': ('last_login', 'last_active_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    inlines = [UserAuthProviderInline]
    list_per_page = 50
    ordering = ('-created_at',)

    actions = ['make_active', 'make_inactive', 'ban_users', 'unban_users']

    def avatar_tag(self, obj):
        if obj.avatar:
            return format_html(
                '<img src="{}" width="32" height="32" style="border-radius:50%;"/>',
                obj.avatar
            )
        return '-'
    avatar_tag.short_description = '头像'

    def phone_masked(self, obj):
        if obj.phone and len(obj.phone) >= 7:
            return f"{obj.phone[:3]}****{obj.phone[-4:]}"
        return obj.phone or '-'
    phone_masked.short_description = '手机号'

    def vip_tag(self, obj):
        if not obj.is_vip:
            return '-'
        if obj.vip_expired_at and obj.vip_expired_at < timezone.now():
            return mark_safe('<span style="color:#999;">已过期</span>')
        return format_html(
            '<span style="color:#ffa500;">VIP{}</span>',
            obj.vip_level
        )
    vip_tag.short_description = 'VIP'

    def social_tag(self, obj):           # ★ 粉丝 / 帖子 概要
        return format_html(
            '粉丝 {} · 帖 {}',
            obj.followers_count, obj.posts_count
        )
    social_tag.short_description = '社交'

    def status_tag(self, obj):
        if obj.is_banned:
            return mark_safe('<span style="color:#dc3545;">封禁</span>')
        if not obj.is_active:
            return mark_safe('<span style="color:#999;">禁用</span>')
        return mark_safe('<span style="color:#28a745;">正常</span>')
    status_tag.short_description = '状态'

    def make_active(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'已激活 {count} 个用户')
    make_active.short_description = '激活用户'

    def make_inactive(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'已禁用 {count} 个用户')
    make_inactive.short_description = '禁用用户'

    def ban_users(self, request, queryset):
        count = queryset.update(is_banned=True, ban_reason='后台封禁')
        self.message_user(request, f'已封禁 {count} 个用户')
    ban_users.short_description = '封禁用户'

    def unban_users(self, request, queryset):
        count = queryset.update(is_banned=False, ban_reason='')
        self.message_user(request, f'已解封 {count} 个用户')
    unban_users.short_description = '解封用户'


@admin.register(UserAuthProvider)
class UserAuthProviderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'provider', 'provider_uid', 'created_at')
    list_filter = ('provider', 'created_at')
    search_fields = ('user__username', 'user__phone', 'provider_uid')
    readonly_fields = ('user', 'provider', 'provider_uid', 'union_id', 'created_at')
    list_per_page = 50


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'platform', 'device_model',
        'app_version', 'is_active', 'last_active_at'
    )
    list_filter = ('platform', 'is_active', 'last_active_at')
    search_fields = ('user__username', 'user__phone', 'device_id')
    list_per_page = 50


@admin.register(UserLoginLog)
class UserLoginLogAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'login_method', 'platform',
        'ip_address', 'is_success', 'created_at'
    )
    list_filter = ('login_method', 'platform', 'is_success', 'created_at')
    search_fields = ('user__username', 'user__phone', 'ip_address')
    readonly_fields = ('user', 'login_method', 'platform', 'ip_address', 'created_at')
    list_per_page = 100

    def has_add_permission(self, request):
        return False


admin.site.site_header = '用户管理'
admin.site.site_title = '用户管理'