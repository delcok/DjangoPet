# -*- coding: utf-8 -*-
# @Time    : 2025/11/04
# @Author  : Modified for new order system

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils import timezone

from bill.models import Bill, ServiceOrder


@admin.register(ServiceOrder)
class ServiceOrderAdmin(admin.ModelAdmin):
    """服务订单管理界面"""

    list_display = [
        'order_number', 'user_link', 'base_service_display',
        'pets_count', 'additional_services_count',
        'scheduled_datetime', 'price_display', 'status_badge',
        'payment_status', 'staff_link', 'created_at'
    ]

    list_filter = [
        'status',
        ('scheduled_date', admin.DateFieldListFilter),
        ('created_at', admin.DateFieldListFilter),
        ('paid_at', admin.DateFieldListFilter),
        'base_service',
        'staff'
    ]

    search_fields = [
        'id', 'service_address', 'contact_phone', 'contact_name',
        'customer_notes', 'user__username', 'user__phone',
        'staff__name', 'base_service__name'
    ]

    readonly_fields = [
        'id', 'base_price', 'additional_price', 'total_price',
        'final_price', 'created_at', 'updated_at', 'paid_at',
        'completed_at', 'display_additional_services',
        'display_price_breakdown', 'display_payment_info',
        'display_status_history'
    ]

    date_hierarchy = 'scheduled_date'
    ordering = ['-created_at']
    filter_horizontal = ['pets', 'additional_services']

    list_per_page = 20

    fieldsets = (
        ('订单信息', {
            'fields': ('id', 'user', 'status', 'staff')
        }),
        ('服务内容', {
            'fields': (
                'base_service',
                'additional_services',
                'display_additional_services',
                'pets'
            )
        }),
        ('预约信息', {
            'fields': (
                'scheduled_date', 'scheduled_time', 'duration_minutes',
                'service_address', 'contact_phone', 'contact_name'
            )
        }),
        ('价格信息', {
            'fields': (
                'display_price_breakdown',
                'base_price', 'additional_price', 'total_price',
                'discount_amount', 'final_price'
            )
        }),
        ('支付信息', {
            'fields': ('display_payment_info',),
            'classes': ('collapse',)
        }),
        ('备注信息', {
            'fields': ('customer_notes', 'staff_notes', 'cancel_reason'),
            'classes': ('collapse',)
        }),
        ('时间记录', {
            'fields': (
                'created_at', 'updated_at', 'paid_at', 'completed_at',
                'display_status_history'
            ),
            'classes': ('collapse',)
        }),
    )

    def order_number(self, obj):
        """订单编号"""
        return format_html(
            '<strong style="color: #007bff;">#{}</strong>',
            str(obj.id).zfill(6)
        )

    order_number.short_description = '订单号'
    order_number.admin_order_field = 'id'

    def user_link(self, obj):
        """用户链接"""
        if obj.user:
            url = reverse('admin:user_user_change', args=[obj.user.id])
            return format_html(
                '<a href="{}" style="text-decoration: none;">'
                '<span style="color: #007bff;">{}</span><br>'
                '<small style="color: #6c757d;">{}</small></a>',
                url, obj.user.username,
                getattr(obj.user, 'phone', '未设置')
            )
        return '-'

    user_link.short_description = '用户'

    def base_service_display(self, obj):
        """基础服务显示"""
        if obj.base_service:
            return format_html(
                '<span style="color: #007bff; font-weight: bold;">{}</span><br>'
                '<small style="color: #6c757d;">¥{:.2f}</small>',
                obj.base_service.name,
                obj.base_price
            )
        return '-'

    base_service_display.short_description = '基础服务'

    def pets_count(self, obj):
        """宠物数量和详情"""
        count = obj.pets.count()
        if count > 0:
            pets_info = []
            for pet in obj.pets.all()[:3]:
                pets_info.append(f"{pet.name}({pet.pet_type.name if hasattr(pet, 'pet_type') else ''})")
            pets_names = ', '.join(pets_info)
            if count > 3:
                pets_names += f' 等{count}只'
            return format_html(
                '<span title="{}" style="cursor: help;">{} 只</span>',
                pets_names,
                count
            )
        return format_html('<span style="color: #dc3545;">未选择</span>')

    pets_count.short_description = '宠物'

    def additional_services_count(self, obj):
        """附加服务数量"""
        count = obj.additional_services.count()
        if count > 0:
            services_names = ', '.join([s.name for s in obj.additional_services.all()[:3]])
            total_price = sum(s.price for s in obj.additional_services.all())
            if count > 3:
                services_names += f' 等{count}项'
            return format_html(
                '<span title="{}" style="color: #28a745; cursor: help;">'
                '{} 项 (¥{:.2f})</span>',
                services_names,
                count,
                total_price
            )
        return format_html('<span style="color: #6c757d;">无</span>')

    additional_services_count.short_description = '附加服务'

    def scheduled_datetime(self, obj):
        """预约时间"""
        return format_html(
            '<span style="font-weight: bold;">{}</span><br>'
            '<span style="color: #6c757d;">{}</span>',
            obj.scheduled_date.strftime('%Y-%m-%d'),
            obj.scheduled_time.strftime('%H:%M')
        )

    scheduled_datetime.short_description = '预约时间'
    scheduled_datetime.admin_order_field = 'scheduled_date'

    def price_display(self, obj):
        """价格显示"""
        if obj.discount_amount > 0:
            return format_html(
                '<span style="text-decoration: line-through; color: #6c757d;">¥{:.2f}</span><br>'
                '<span style="color: #dc3545; font-weight: bold;">¥{:.2f}</span>',
                obj.total_price,
                obj.final_price
            )
        return format_html(
            '<span style="font-weight: bold;">¥{:.2f}</span>',
            obj.final_price
        )

    price_display.short_description = '订单金额'
    price_display.admin_order_field = 'final_price'

    def status_badge(self, obj):
        """状态徽章"""
        colors = {
            'draft': '#6c757d',  # 灰色 - 待支付
            'paid': '#ffc107',  # 黄色 - 已支付
            'confirmed': '#17a2b8',  # 青色 - 已确认
            'assigned': '#fd7e14',  # 橙色 - 已分配
            'in_progress': '#007bff',  # 蓝色 - 服务中
            'completed': '#28a745',  # 绿色 - 已完成
            'cancelled': '#dc3545',  # 红色 - 已取消
            'refunded': '#6f42c1'  # 紫色 - 已退款
        }
        color = colors.get(obj.status, '#6c757d')
        icon = ''
        if obj.status == 'completed':
            icon = '✓ '
        elif obj.status == 'cancelled':
            icon = '✗ '
        elif obj.status == 'refunded':
            icon = '↩ '

        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 8px; '
            'border-radius: 4px; font-size: 12px; white-space: nowrap;">'
            '{}{}</span>',
            color,
            icon,
            obj.get_status_display()
        )

    status_badge.short_description = '订单状态'

    def payment_status(self, obj):
        """支付状态"""
        # 获取最新的支付账单
        latest_bill = obj.bills.filter(transaction_type='payment').order_by('-created_at').first()

        if not latest_bill:
            if obj.status == 'draft':
                return format_html('<span style="color: #ffc107;">待创建支付</span>')
            else:
                return format_html('<span style="color: #6c757d;">无支付记录</span>')

        status_colors = {
            'pending': '#ffc107',
            'processing': '#17a2b8',
            'success': '#28a745',
            'failed': '#dc3545',
            'cancelled': '#6c757d',
            'refunded': '#6f42c1'
        }

        color = status_colors.get(latest_bill.payment_status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span><br>'
            '<small style="color: #6c757d;">{}</small>',
            color,
            latest_bill.get_payment_status_display(),
            latest_bill.out_trade_no[:15] + '...' if len(latest_bill.out_trade_no) > 15 else latest_bill.out_trade_no
        )

    payment_status.short_description = '支付状态'

    def staff_link(self, obj):
        """员工链接"""
        if obj.staff:
            return format_html(
                '<span style="color: green; font-weight: bold;">{}</span>',
                obj.staff.name
            )
        elif obj.status in ['draft', 'paid']:
            return format_html('<span style="color: #ffc107;">待分配</span>')
        else:
            return format_html('<span style="color: #dc3545;">未分配</span>')

    staff_link.short_description = '服务员工'

    def display_additional_services(self, obj):
        """显示附加服务详情"""
        if obj.pk:
            services = obj.additional_services.all()
            if services:
                html = '<div style="max-width: 600px;">'
                html += '<table style="width: 100%; border-collapse: collapse;">'
                html += '<thead><tr style="background-color: #f8f9fa;">'
                html += '<th style="padding: 8px; text-align: left; border: 1px solid #dee2e6;">服务名称</th>'
                html += '<th style="padding: 8px; text-align: right; border: 1px solid #dee2e6;">价格</th>'
                html += '</tr></thead><tbody>'

                total = 0
                for service in services:
                    html += '<tr>'
                    html += f'<td style="padding: 8px; border: 1px solid #dee2e6;">{service.name}</td>'
                    html += f'<td style="padding: 8px; text-align: right; border: 1px solid #dee2e6;">¥{service.price:.2f}</td>'
                    html += '</tr>'
                    total += service.price

                html += '</tbody><tfoot>'
                html += '<tr style="background-color: #f8f9fa; font-weight: bold;">'
                html += '<td style="padding: 8px; border: 1px solid #dee2e6;">合计</td>'
                html += f'<td style="padding: 8px; text-align: right; border: 1px solid #dee2e6;">¥{total:.2f}</td>'
                html += '</tr></tfoot></table></div>'

                return mark_safe(html)
            return '无附加服务'
        return '保存后显示'

    display_additional_services.short_description = '附加服务明细'

    def display_price_breakdown(self, obj):
        """价格明细"""
        if obj.pk:
            html = '<div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; max-width: 400px;">'
            html += f'<div style="margin-bottom: 10px;">基础服务: <span style="float: right;">¥{obj.base_price:.2f}</span></div>'
            html += f'<div style="margin-bottom: 10px;">附加服务: <span style="float: right;">¥{obj.additional_price:.2f}</span></div>'
            html += '<hr style="border: 1px solid #dee2e6;">'
            html += f'<div style="margin-bottom: 10px;">小计: <span style="float: right;">¥{obj.total_price:.2f}</span></div>'

            if obj.discount_amount > 0:
                html += f'<div style="margin-bottom: 10px; color: #dc3545;">优惠: <span style="float: right;">-¥{obj.discount_amount:.2f}</span></div>'
                html += '<hr style="border: 1px solid #dee2e6;">'

            html += f'<div style="font-weight: bold; font-size: 16px;">应付金额: <span style="float: right; color: #dc3545;">¥{obj.final_price:.2f}</span></div>'
            html += '</div>'

            return mark_safe(html)
        return '保存后显示'

    display_price_breakdown.short_description = '价格明细'

    def display_payment_info(self, obj):
        """支付信息"""
        if obj.pk:
            bills = obj.bills.all().order_by('-created_at')
            if bills:
                html = '<div style="max-width: 800px;">'
                html += '<table style="width: 100%; border-collapse: collapse;">'
                html += '<thead><tr style="background-color: #f8f9fa;">'
                html += '<th style="padding: 8px; border: 1px solid #dee2e6;">订单号</th>'
                html += '<th style="padding: 8px; border: 1px solid #dee2e6;">类型</th>'
                html += '<th style="padding: 8px; border: 1px solid #dee2e6;">金额</th>'
                html += '<th style="padding: 8px; border: 1px solid #dee2e6;">支付方式</th>'
                html += '<th style="padding: 8px; border: 1px solid #dee2e6;">状态</th>'
                html += '<th style="padding: 8px; border: 1px solid #dee2e6;">时间</th>'
                html += '</tr></thead><tbody>'

                for bill in bills[:5]:  # 只显示最近5条
                    html += '<tr>'
                    html += f'<td style="padding: 8px; border: 1px solid #dee2e6; font-size: 12px;">{bill.out_trade_no}</td>'
                    html += f'<td style="padding: 8px; border: 1px solid #dee2e6;">{bill.get_transaction_type_display()}</td>'
                    html += f'<td style="padding: 8px; border: 1px solid #dee2e6;">¥{bill.amount:.2f}</td>'
                    html += f'<td style="padding: 8px; border: 1px solid #dee2e6;">{bill.get_payment_method_display()}</td>'

                    status_color = '#28a745' if bill.payment_status == 'success' else '#ffc107'
                    html += f'<td style="padding: 8px; border: 1px solid #dee2e6; color: {status_color};">{bill.get_payment_status_display()}</td>'
                    html += f'<td style="padding: 8px; border: 1px solid #dee2e6; font-size: 12px;">{bill.created_at.strftime("%Y-%m-%d %H:%M")}</td>'
                    html += '</tr>'

                html += '</tbody></table></div>'
                return mark_safe(html)
            return '暂无支付记录'
        return '保存后显示'

    display_payment_info.short_description = '支付记录'

    def display_status_history(self, obj):
        """状态变更历史（简化版）"""
        if obj.pk:
            html = '<div style="max-width: 500px;">'

            if obj.created_at:
                html += f'<div style="margin-bottom: 5px;">📝 创建订单: {obj.created_at.strftime("%Y-%m-%d %H:%M:%S")}</div>'

            if obj.paid_at:
                html += f'<div style="margin-bottom: 5px;">💰 支付成功: {obj.paid_at.strftime("%Y-%m-%d %H:%M:%S")}</div>'

            if obj.completed_at:
                html += f'<div style="margin-bottom: 5px;">✅ 完成服务: {obj.completed_at.strftime("%Y-%m-%d %H:%M:%S")}</div>'

            if obj.status == 'cancelled' and obj.cancel_reason:
                html += f'<div style="margin-bottom: 5px; color: #dc3545;">❌ 取消原因: {obj.cancel_reason}</div>'

            html += '</div>'
            return mark_safe(html)
        return '保存后显示'

    display_status_history.short_description = '状态历史'

    def get_queryset(self, request):
        """优化查询"""
        return super().get_queryset(request).select_related(
            'user', 'staff', 'base_service'
        ).prefetch_related(
            'pets', 'additional_services', 'bills'
        )

    actions = ['confirm_orders', 'assign_staff', 'complete_orders', 'cancel_orders', 'export_orders']

    def confirm_orders(self, request, queryset):
        """批量确认订单"""
        updated = queryset.filter(status='paid').update(
            status='confirmed'
        )
        self.message_user(request, f'成功确认 {updated} 个订单')

    confirm_orders.short_description = '✓ 确认选中的订单'

    def assign_staff(self, request, queryset):
        """批量分配员工（这里需要更复杂的逻辑）"""
        # 这里简化处理，实际需要一个分配界面
        updated = queryset.filter(status='confirmed').update(
            status='assigned'
        )
        self.message_user(request, f'已标记 {updated} 个订单为已分配（请手动指定员工）')

    assign_staff.short_description = '👤 分配员工'

    def complete_orders(self, request, queryset):
        """批量完成订单"""
        updated = queryset.filter(status='in_progress').update(
            status='completed',
            completed_at=timezone.now()
        )
        self.message_user(request, f'成功完成 {updated} 个订单')

    complete_orders.short_description = '✅ 完成选中的订单'

    def cancel_orders(self, request, queryset):
        """批量取消订单"""
        updated = queryset.filter(
            status__in=['draft', 'paid', 'confirmed']
        ).update(
            status='cancelled',
            cancel_reason='管理员批量取消'
        )
        self.message_user(request, f'成功取消 {updated} 个订单')

    cancel_orders.short_description = '✗ 取消选中的订单'

    def export_orders(self, request, queryset):
        """导出订单（简化版）"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response[
            'Content-Disposition'] = f'attachment; filename="orders_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            '订单号', '用户', '基础服务', '附加服务', '预约时间',
            '地址', '联系电话', '总价', '状态', '创建时间'
        ])

        for order in queryset:
            writer.writerow([
                order.id,
                order.user.username if order.user else '',
                order.base_service.name if order.base_service else '',
                ', '.join([s.name for s in order.additional_services.all()]),
                f"{order.scheduled_date} {order.scheduled_time}",
                order.service_address,
                order.contact_phone,
                order.final_price,
                order.get_status_display(),
                order.created_at.strftime("%Y-%m-%d %H:%M:%S")
            ])

        return response

    export_orders.short_description = '📥 导出选中的订单'

    def save_model(self, request, obj, form, change):
        """保存时自动计算价格"""
        if not change:  # 新建时
            obj.calculate_prices()
        super().save_model(request, obj, form, change)

        # 如果是更新附加服务，重新计算价格
        if change and 'additional_services' in form.changed_data:
            obj.calculate_prices()
            obj.save()


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    """账单管理界面"""

    list_display = [
        'trade_no_display', 'user_link', 'service_order_link',
        'transaction_type_badge', 'amount_display',
        'payment_method_badge', 'payment_status_badge',
        'created_time', 'paid_time'
    ]

    list_filter = [
        'transaction_type', 'payment_method', 'payment_status',
        ('created_at', admin.DateFieldListFilter),
        ('paid_at', admin.DateFieldListFilter),
    ]

    search_fields = [
        'out_trade_no', 'third_party_no', 'description',
        'user__username', 'user__phone',
        'service_order__id'
    ]

    readonly_fields = [
        'out_trade_no', 'third_party_no', 'created_at',
        'updated_at', 'paid_at', 'expired_at',
        'display_related_order', 'display_refund_info'
    ]

    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    list_per_page = 30

    fieldsets = (
        ('基本信息', {
            'fields': ('out_trade_no', 'third_party_no', 'user', 'service_order')
        }),
        ('交易信息', {
            'fields': (
                'transaction_type', 'amount', 'payment_method',
                'payment_status', 'description'
            )
        }),
        ('关联订单', {
            'fields': ('display_related_order',),
            'classes': ('collapse',)
        }),
        ('退款信息', {
            'fields': (
                'original_bill', 'refund_amount', 'refund_reason',
                'display_refund_info'
            ),
            'classes': ('collapse',)
        }),
        ('失败信息', {
            'fields': ('failure_reason',),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at', 'paid_at', 'expired_at'),
            'classes': ('collapse',)
        }),
    )

    def trade_no_display(self, obj):
        """订单号显示"""
        return format_html(
            '<div style="font-family: monospace;">'
            '<strong style="color: #007bff;">{}</strong><br>'
            '<small style="color: #6c757d;">{}</small></div>',
            obj.out_trade_no[:20] + '...' if len(obj.out_trade_no) > 20 else obj.out_trade_no,
            obj.third_party_no[:20] + '...' if obj.third_party_no and len(
                obj.third_party_no) > 20 else obj.third_party_no or '无'
        )

    trade_no_display.short_description = '订单号'

    def user_link(self, obj):
        """用户链接"""
        if obj.user:
            url = reverse('admin:user_user_change', args=[obj.user.id])
            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.user.username
            )
        return '-'

    user_link.short_description = '用户'

    def service_order_link(self, obj):
        """服务订单链接"""
        if obj.service_order:
            url = reverse('admin:bill_serviceorder_change', args=[obj.service_order.id])
            return format_html(
                '<a href="{}" style="text-decoration: none;">'
                '<span style="color: #007bff;">订单#{}</span></a>',
                url,
                str(obj.service_order.id).zfill(6)
            )
        return format_html('<span style="color: #6c757d;">-</span>')

    service_order_link.short_description = '服务订单'

    def transaction_type_badge(self, obj):
        """交易类型徽章"""
        colors = {
            'payment': '#28a745',  # 绿色 - 支付
            'refund': '#dc3545',  # 红色 - 退款
            'recharge': '#007bff',  # 蓝色 - 充值
            'withdraw': '#ffc107'  # 黄色 - 提现
        }
        icons = {
            'payment': '💳',
            'refund': '↩',
            'recharge': '➕',
            'withdraw': '➖'
        }
        color = colors.get(obj.transaction_type, '#6c757d')
        icon = icons.get(obj.transaction_type, '')

        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 12px;">{} {}</span>',
            color,
            icon,
            obj.get_transaction_type_display()
        )

    transaction_type_badge.short_description = '交易类型'

    def amount_display(self, obj):
        """金额显示"""
        if obj.transaction_type == 'refund':
            color = '#dc3545'
            sign = '-'
        elif obj.transaction_type == 'withdraw':
            color = '#ffc107'
            sign = '-'
        else:
            color = '#28a745'
            sign = '+'

        return format_html(
            '<span style="color: {}; font-weight: bold; font-size: 14px;">'
            '{}¥{:.2f}</span>',
            color,
            sign,
            obj.amount
        )

    amount_display.short_description = '金额'
    amount_display.admin_order_field = 'amount'

    def payment_method_badge(self, obj):
        """支付方式徽章"""
        icons = {
            'wechat': '🟢',
            'alipay': '🔵',
            'balance': '💰',
            'cash': '💵',
            'other': '📱'
        }
        icon = icons.get(obj.payment_method, '')

        return format_html(
            '<span>{} {}</span>',
            icon,
            obj.get_payment_method_display()
        )

    payment_method_badge.short_description = '支付方式'

    def payment_status_badge(self, obj):
        """支付状态徽章"""
        colors = {
            'pending': '#ffc107',  # 黄色 - 待支付
            'processing': '#17a2b8',  # 青色 - 处理中
            'success': '#28a745',  # 绿色 - 成功
            'failed': '#dc3545',  # 红色 - 失败
            'cancelled': '#6c757d',  # 灰色 - 已取消
            'refunded': '#6f42c1'  # 紫色 - 已退款
        }
        color = colors.get(obj.payment_status, '#6c757d')

        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 12px;">{}</span>',
            color,
            obj.get_payment_status_display()
        )

    payment_status_badge.short_description = '支付状态'

    def created_time(self, obj):
        """创建时间"""
        return obj.created_at.strftime('%Y-%m-%d %H:%M:%S')

    created_time.short_description = '创建时间'
    created_time.admin_order_field = 'created_at'

    def paid_time(self, obj):
        """支付时间"""
        if obj.paid_at:
            return format_html(
                '<span style="color: #28a745;">{}</span>',
                obj.paid_at.strftime('%Y-%m-%d %H:%M:%S')
            )
        return format_html('<span style="color: #6c757d;">-</span>')

    paid_time.short_description = '支付时间'
    paid_time.admin_order_field = 'paid_at'

    def display_related_order(self, obj):
        """关联订单信息"""
        if obj.service_order:
            order = obj.service_order
            html = '<div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px;">'
            html += f'<p><strong>订单号:</strong> #{str(order.id).zfill(6)}</p>'
            html += f'<p><strong>用户:</strong> {order.user.username if order.user else "-"}</p>'
            html += f'<p><strong>服务:</strong> {order.base_service.name if order.base_service else "-"}</p>'
            html += f'<p><strong>预约时间:</strong> {order.scheduled_date} {order.scheduled_time}</p>'
            html += f'<p><strong>订单金额:</strong> ¥{order.final_price:.2f}</p>'
            html += f'<p><strong>订单状态:</strong> {order.get_status_display()}</p>'
            html += '</div>'
            return mark_safe(html)
        return '无关联订单'

    display_related_order.short_description = '关联订单详情'

    def display_refund_info(self, obj):
        """退款信息详情"""
        if obj.transaction_type == 'refund' and obj.original_bill:
            original = obj.original_bill
            html = '<div style="background-color: #fff5f5; padding: 15px; border-radius: 5px;">'
            html += f'<p><strong>原支付订单:</strong> {original.out_trade_no}</p>'
            html += f'<p><strong>原支付金额:</strong> ¥{original.amount:.2f}</p>'
            html += f'<p><strong>退款金额:</strong> ¥{obj.refund_amount:.2f}</p>'
            html += f'<p><strong>退款原因:</strong> {obj.refund_reason or "未说明"}</p>'
            html += '</div>'
            return mark_safe(html)
        return '非退款订单'

    display_refund_info.short_description = '退款详情'

    def get_queryset(self, request):
        """优化查询"""
        return super().get_queryset(request).select_related(
            'user', 'service_order', 'original_bill'
        )

    actions = ['mark_as_paid', 'mark_as_failed', 'export_bills']

    def mark_as_paid(self, request, queryset):
        """标记为已支付（仅用于测试）"""
        updated = 0
        for bill in queryset.filter(payment_status='pending'):
            bill.mark_as_paid()
            updated += 1
        self.message_user(request, f'成功标记 {updated} 个账单为已支付')

    mark_as_paid.short_description = '✓ 标记为已支付（测试用）'

    def mark_as_failed(self, request, queryset):
        """标记为支付失败"""
        updated = 0
        for bill in queryset.filter(payment_status='pending'):
            bill.mark_as_failed('管理员手动标记')
            updated += 1
        self.message_user(request, f'成功标记 {updated} 个账单为失败')

    mark_as_failed.short_description = '✗ 标记为支付失败'

    def export_bills(self, request, queryset):
        """导出账单"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="bills_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        # 添加 UTF-8 BOM
        response.write('\ufeff')

        writer = csv.writer(response)
        writer.writerow([
            '账单号', '用户', '服务订单', '交易类型', '金额',
            '支付方式', '支付状态', '创建时间', '支付时间'
        ])

        for bill in queryset:
            writer.writerow([
                bill.out_trade_no,
                bill.user.username if bill.user else '',
                f"#{bill.service_order.id}" if bill.service_order else '',
                bill.get_transaction_type_display(),
                bill.amount,
                bill.get_payment_method_display(),
                bill.get_payment_status_display(),
                bill.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                bill.paid_at.strftime("%Y-%m-%d %H:%M:%S") if bill.paid_at else ''
            ])

        return response

    export_bills.short_description = '📥 导出选中的账单'