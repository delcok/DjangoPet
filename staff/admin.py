# -*- coding: utf-8 -*-
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db.models import Count, Q
from .models import Staff


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    """员工管理后台 - 增强版"""

    # 列表页显示字段
    list_display = [
        'id',
        'avatar_preview',
        'username',
        'phone',
        'gender_display',
        'age_display',
        'integral_display',
        'is_worked_badge',
        'is_active_badge',
        'orders_count',
        'last_login_display',
        'created_at',
    ]

    # 列表页过滤器
    list_filter = [
        'is_active',
        'is_worked',
        'gender',
        ('created_at', admin.DateFieldListFilter),
        ('last_login', admin.DateFieldListFilter),
        ('birth_date', admin.EmptyFieldListFilter),
    ]

    # 搜索字段
    search_fields = [
        'username',
        'phone',
        'openid',
        'unionid',
        'id',
    ]

    # 可点击进入详情的字段
    list_display_links = ['id', 'username']

    # 可在列表页直接编辑的字段
    list_editable = [
        'is_active',
        'is_worked',
    ]

    # 排序
    ordering = ['-created_at']

    # 每页显示数量
    list_per_page = 25

    # 详情页字段分组
    fieldsets = (
        ('基本信息', {
            'fields': (
                'username',
                'avatar',
                ('phone', 'gender'),
                'birth_date',
            )
        }),
        ('微信信息', {
            'fields': ('openid', 'unionid'),
            'classes': ('collapse',),
            'description': '微信小程序相关的唯一标识符'
        }),
        ('积分与状态', {
            'fields': (
                'integral',
                ('is_active', 'is_worked'),
            ),
            'classes': ('wide',),
        }),
        ('时间信息', {
            'fields': (
                'last_login',
                ('created_at', 'updated_at'),
            ),
            'classes': ('collapse',),
        }),
    )

    # 只读字段
    readonly_fields = ['created_at', 'updated_at', 'last_login']

    # 日期层级过滤
    date_hierarchy = 'created_at'

    # 自定义操作
    actions = [
        'activate_staff',
        'deactivate_staff',
        'set_working',
        'set_not_working',
        'add_integral',
        'export_to_csv',
    ]

    # 添加额外的CSS和JS
    class Media:
        css = {
            'all': ('admin/css/custom_staff_admin.css',)
        }
        js = ('admin/js/custom_staff_admin.js',)

    def get_queryset(self, request):
        """优化查询性能"""
        queryset = super().get_queryset(request)
        # 预加载关联数据，避免 N+1 查询
        queryset = queryset.annotate(
            _orders_count=Count('service_orders', distinct=True)
        )
        return queryset

    # ========== 自定义显示字段 ==========

    def avatar_preview(self, obj):
        """头像预览"""
        if obj.avatar:
            return format_html(
                '<img src="{}" width="50" height="50" style="border-radius: 50%; '
                'object-fit: cover; border: 2px solid #ddd;" />',
                obj.avatar
            )
        # 显示首字母头像
        initial = obj.username[0].upper() if obj.username else '?'
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8']
        color = colors[hash(obj.username or '') % len(colors)]
        return format_html(
            '<div style="width:50px;height:50px;border-radius:50%;background:{};'
            'display:flex;align-items:center;justify-content:center;color:#fff;'
            'font-size:20px;font-weight:bold;">{}</div>',
            color, initial
        )

    avatar_preview.short_description = '头像'

    def gender_display(self, obj):
        """性别显示"""
        gender_config = {
            'M': ('👨 男', '#2196F3'),
            'F': ('👩 女', '#E91E63'),
            'U': ('❓ 未知', '#9E9E9E')
        }
        text, color = gender_config.get(obj.gender, ('未知', '#9E9E9E'))
        return format_html(
            '<span style="color: {}; font-weight: 500;">{}</span>',
            color, text
        )

    gender_display.short_description = '性别'

    def age_display(self, obj):
        """年龄显示"""
        if obj.birth_date:
            from datetime import date
            today = date.today()
            age = today.year - obj.birth_date.year - (
                    (today.month, today.day) < (obj.birth_date.month, obj.birth_date.day)
            )
            if age < 18:
                color = '#FF9800'
            elif age < 30:
                color = '#4CAF50'
            elif age < 50:
                color = '#2196F3'
            else:
                color = '#9E9E9E'
            return format_html(
                '<span style="color: {}; font-weight: 500;">{}岁</span>',
                color, age
            )
        return format_html('<span style="color: #ccc;">-</span>')

    age_display.short_description = '年龄'

    def integral_display(self, obj):
        """积分显示"""
        if obj.integral >= 1000:
            color = '#FFD700'
            icon = '🌟'
        elif obj.integral >= 500:
            color = '#4CAF50'
            icon = '⭐'
        elif obj.integral >= 100:
            color = '#2196F3'
            icon = '✨'
        else:
            color = '#9E9E9E'
            icon = '💎'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            color, icon, obj.integral
        )

    integral_display.short_description = '积分'
    integral_display.admin_order_field = 'integral'

    def is_active_badge(self, obj):
        """激活状态标签"""
        if obj.is_active:
            return format_html(
                '<span style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); '
                'color: white; padding: 4px 12px; border-radius: 12px; font-size: 11px; '
                'font-weight: 500; display: inline-block;">✓ 激活</span>'
            )
        return format_html(
            '<span style="background: #f44336; color: white; padding: 4px 12px; '
            'border-radius: 12px; font-size: 11px; font-weight: 500; display: inline-block;">'
            '✗ 停用</span>'
        )

    is_active_badge.short_description = '账户状态'
    is_active_badge.admin_order_field = 'is_active'

    def is_worked_badge(self, obj):
        """工作状态标签"""
        if obj.is_worked:
            return format_html(
                '<span style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); '
                'color: white; padding: 4px 12px; border-radius: 12px; font-size: 11px; '
                'font-weight: 500; display: inline-block;">🔥 工作中</span>'
            )
        return format_html(
            '<span style="background: #9E9E9E; color: white; padding: 4px 12px; '
            'border-radius: 12px; font-size: 11px; font-weight: 500; display: inline-block;">'
            '💤 休息中</span>'
        )

    is_worked_badge.short_description = '工作状态'
    is_worked_badge.admin_order_field = 'is_worked'

    def orders_count(self, obj):
        """订单数量"""
        count = getattr(obj, '_orders_count', 0)
        if count > 0:
            # 创建链接到该员工的订单列表
            url = reverse('admin:bill_serviceorder_changelist') + f'?staff__id__exact={obj.id}'
            return format_html(
                '<a href="{}" style="color: #2196F3; font-weight: 500;">'
                '📋 {} 单</a>',
                url, count
            )
        return format_html('<span style="color: #ccc;">0</span>')

    orders_count.short_description = '订单数'
    orders_count.admin_order_field = '_orders_count'

    def last_login_display(self, obj):
        """最后登录时间显示"""
        if obj.last_login:
            from django.utils.timezone import now
            diff = now() - obj.last_login

            if diff.days == 0:
                if diff.seconds < 3600:
                    time_str = f'{diff.seconds // 60}分钟前'
                    color = '#4CAF50'
                else:
                    time_str = f'{diff.seconds // 3600}小时前'
                    color = '#4CAF50'
            elif diff.days < 7:
                time_str = f'{diff.days}天前'
                color = '#FF9800'
            elif diff.days < 30:
                time_str = f'{diff.days}天前'
                color = '#FF5722'
            else:
                time_str = obj.last_login.strftime('%Y-%m-%d')
                color = '#9E9E9E'

            return format_html(
                '<span style="color: {};">{}</span>',
                color, time_str
            )
        return format_html('<span style="color: #ccc;">从未登录</span>')

    last_login_display.short_description = '最后登录'
    last_login_display.admin_order_field = 'last_login'

    # ========== 批量操作 ==========

    def activate_staff(self, request, queryset):
        """批量激活员工"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'✓ 成功激活 {updated} 个员工账户', level='SUCCESS')

    activate_staff.short_description = '✓ 激活选中的员工'

    def deactivate_staff(self, request, queryset):
        """批量停用员工"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'✗ 成功停用 {updated} 个员工账户', level='WARNING')

    deactivate_staff.short_description = '✗ 停用选中的员工'

    def set_working(self, request, queryset):
        """批量设置为工作状态"""
        updated = queryset.update(is_worked=True)
        self.message_user(request, f'🔥 成功设置 {updated} 个员工为工作状态', level='SUCCESS')

    set_working.short_description = '🔥 设置为工作中'

    def set_not_working(self, request, queryset):
        """批量设置为休息状态"""
        updated = queryset.update(is_worked=False)
        self.message_user(request, f'💤 成功设置 {updated} 个员工为休息状态', level='INFO')

    set_not_working.short_description = '💤 设置为休息中'

    def add_integral(self, request, queryset):
        """批量增加积分"""
        # 这里可以改成从表单输入积分数
        updated = queryset.update(integral=models.F('integral') + 10)
        self.message_user(request, f'💎 成功为 {updated} 个员工增加 10 积分', level='SUCCESS')

    add_integral.short_description = '💎 增加 10 积分'

    def export_to_csv(self, request, queryset):
        """导出为CSV"""
        import csv
        from django.http import HttpResponse
        from datetime import datetime

        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="staff_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow(['ID', '用户名', '手机号', '性别', '出生日期', '积分', '账户状态', '工作状态', '创建时间'])

        for staff in queryset:
            writer.writerow([
                staff.id,
                staff.username,
                staff.phone,
                staff.get_gender_display(),
                staff.birth_date,
                staff.integral,
                '激活' if staff.is_active else '停用',
                '工作中' if staff.is_worked else '休息中',
                staff.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])

        self.message_user(request, f'📊 成功导出 {queryset.count()} 条员工数据', level='SUCCESS')
        return response

    export_to_csv.short_description = '📊 导出为 CSV'

    # ========== 自定义视图增强 ==========

    def changelist_view(self, request, extra_context=None):
        """添加统计信息到列表页"""
        extra_context = extra_context or {}

        # 统计数据
        queryset = self.get_queryset(request)
        total_staff = queryset.count()
        active_staff = queryset.filter(is_active=True).count()
        working_staff = queryset.filter(is_worked=True).count()
        inactive_staff = total_staff - active_staff

        # 添加统计信息
        extra_context.update({
            'total_staff': total_staff,
            'active_staff': active_staff,
            'inactive_staff': inactive_staff,
            'working_staff': working_staff,
            'resting_staff': active_staff - working_staff,
            'active_percentage': round(active_staff / total_staff * 100, 1) if total_staff > 0 else 0,
        })

        return super().changelist_view(request, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        """保存时的额外处理"""
        if not change:  # 新建时
            # 可以在这里添加创建员工时的逻辑
            pass
        super().save_model(request, obj, form, change)