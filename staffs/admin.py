# staffs/admin.py

from django.contrib import admin, messages
from django.utils.html import format_html

from .models import Staff, StaffSchedule, StaffTimeSlot


# ══════════════════════════════════════════════════════════════
# Inline
# ══════════════════════════════════════════════════════════════

class StaffScheduleInline(admin.TabularInline):
    model           = StaffSchedule
    extra           = 0
    fields          = ['date', 'is_working', 'start_time', 'end_time', 'max_orders', 'source', 'note']
    readonly_fields = ['source']
    ordering        = ['date']
    show_change_link = True


class StaffTimeSlotInline(admin.TabularInline):
    model           = StaffTimeSlot
    extra           = 0
    fields          = ['date', 'start_time', 'end_time', 'service_order', 'status']
    readonly_fields = ['date', 'start_time', 'end_time', 'service_order', 'status']
    ordering        = ['-date', 'start_time']
    can_delete      = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


# ══════════════════════════════════════════════════════════════
# Staff
# ══════════════════════════════════════════════════════════════

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'name', 'real_name', 'merchant', 'phone', 'employee_no',
        'status_badge', 'work_status',
        'verification_badge',
        'rating', 'total_orders', 'dispatch_weight',
        'is_recommended', 'created_at',
    ]
    list_filter = [
        'status', 'work_status', 'verification_status',
        'gender', 'is_recommended', 'can_handle_urgent',
    ]
    search_fields = [
        'name', 'real_name', 'phone', 'employee_no',
        'id_card_no', 'merchant__name',
    ]
    ordering = ['-created_at']
    readonly_fields = [
        'rating', 'total_orders', 'monthly_orders', 'total_reviews',
        'good_review_rate', 'avg_response_minutes', 'acceptance_rate',
        'last_login', 'created_at', 'updated_at',
        'current_location_lng', 'current_location_lat', 'location_updated_at',
        'monthly_stat_reset_at', 'token_version', 'login_fail_count', 'locked_until',
        'pending_changes', 'verification_submitted_at', 'verified_at', 'verified_by',
    ]
    filter_horizontal = ['service_categories']
    inlines = [StaffScheduleInline, StaffTimeSlotInline]

    fieldsets = (
        ('基础信息', {
            'fields': (
                'merchant',
                ('name', 'real_name'),
                ('gender', 'birthday', 'avatar'),
                'introduction', 'specialties', 'certificates',
            )
        }),
        ('实名认证(OSS URL)', {
            'fields': (
                'id_card_no',
                ('id_card_front', 'id_card_back'),
                'health_certificate',
            )
        }),
        ('住址信息', {
            'fields': (
                ('province', 'city', 'district'),
                'address',
                ('home_longitude', 'home_latitude'),
            )
        }),
        ('HR 信息', {
            'fields': (
                ('hire_date', 'leave_date', 'work_years'),
                ('emergency_contact_name', 'emergency_contact_phone'),
            )
        }),
        ('实名审核', {
            'fields': (
                'verification_status',
                'pending_changes',
                'verification_remark',
                ('verification_submitted_at', 'verified_at'),
                'verified_by',
            ),
            'description': '员工提交的待审核字段在 pending_changes 中,审核操作请用商家后台 API'
        }),
        ('登录信息', {
            'fields': (
                ('phone', 'employee_no'),
                'password',
            )
        }),
        ('服务能力', {
            'fields': (
                'service_categories',
                ('max_concurrent_orders', 'service_radius'),
                ('can_handle_urgent', 'can_receive_transfer'),
            )
        }),
        ('派单权重', {
            'fields': (
                'dispatch_weight',
                ('avg_response_minutes', 'acceptance_rate'),
            )
        }),
        ('排班设置', {
            'fields': (
                'work_schedule',
                'rest_dates',
            ),
            'classes': ('collapse',),
        }),
        ('实时状态', {
            'fields': (
                'work_status',
                ('current_location_lng', 'current_location_lat', 'location_updated_at'),
            )
        }),
        ('评分与统计', {
            'fields': (
                ('rating', 'good_review_rate'),
                ('total_orders', 'monthly_orders', 'total_reviews'),
                'monthly_stat_reset_at',
            )
        }),
        ('推荐设置', {
            'fields': (
                ('is_recommended', 'sort_order'),
                'recommend_reason',
            )
        }),
        ('状态与安全', {
            'fields': (
                'status',
                ('login_fail_count', 'locked_until'),
                ('token_version', 'last_login'),
            )
        }),
        ('时间戳', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    # ── 列表展示 badges ────────────────────────────
    def status_badge(self, obj):
        colors = {
            Staff.Status.ACTIVE:    '#52c41a',
            Staff.Status.INACTIVE:  '#8c8c8c',
            Staff.Status.SUSPENDED: '#faad14',
        }
        color = colors.get(obj.status, '#8c8c8c')
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = '状态'

    def verification_badge(self, obj):
        colors = {
            Staff.VerificationStatus.UNVERIFIED: '#8c8c8c',
            Staff.VerificationStatus.PENDING:    '#1890ff',
            Staff.VerificationStatus.APPROVED:   '#52c41a',
            Staff.VerificationStatus.REJECTED:   '#f5222d',
        }
        color = colors.get(obj.verification_status, '#8c8c8c')
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>',
            color, obj.get_verification_status_display()
        )
    verification_badge.short_description = '实名审核'

    # ── 批量动作 ────────────────────────────────────
    @admin.action(description='批量暂停选中员工')
    def suspend_staff(self, request, queryset):
        queryset.filter(status=Staff.Status.ACTIVE).update(status=Staff.Status.SUSPENDED)

    @admin.action(description='批量恢复选中员工')
    def activate_staff(self, request, queryset):
        queryset.filter(status=Staff.Status.SUSPENDED).update(status=Staff.Status.ACTIVE)

    @admin.action(description='批量审核通过(应用 pending_changes)')
    def approve_verifications(self, request, queryset):
        ok = 0
        skipped = 0
        for staff in queryset:
            try:
                staff.approve_verification(reviewer=f'admin#{request.user.username}')
                ok += 1
            except ValueError:
                skipped += 1
        self.message_user(
            request,
            f'审核通过 {ok} 个,跳过非待审核状态 {skipped} 个',
            level=messages.SUCCESS,
        )

    actions = ['suspend_staff', 'activate_staff', 'approve_verifications']


# ══════════════════════════════════════════════════════════════
# StaffSchedule
# ══════════════════════════════════════════════════════════════

@admin.register(StaffSchedule)
class StaffScheduleAdmin(admin.ModelAdmin):
    list_display   = ['id', 'staff', 'date', 'is_working', 'start_time', 'end_time', 'max_orders', 'source']
    list_filter    = ['is_working', 'source', 'date']
    search_fields  = ['staff__name', 'staff__phone']
    ordering       = ['-date', 'staff']
    date_hierarchy = 'date'

    fieldsets = (
        (None, {
            'fields': ('staff', 'date', 'is_working', 'source')
        }),
        ('时间', {
            'fields': (
                ('start_time', 'end_time'),
                ('break_start', 'break_end'),
            )
        }),
        ('其他', {
            'fields': ('max_orders', 'note')
        }),
    )


# ══════════════════════════════════════════════════════════════
# StaffTimeSlot
# ══════════════════════════════════════════════════════════════

@admin.register(StaffTimeSlot)
class StaffTimeSlotAdmin(admin.ModelAdmin):
    list_display    = ['id', 'staff', 'service_order', 'date', 'start_time', 'end_time', 'status']
    list_filter     = ['status', 'date']
    search_fields   = ['staff__name', 'service_order__order_no']
    ordering        = ['-date', 'start_time']
    date_hierarchy  = 'date'
    readonly_fields = ['staff', 'service_order', 'date', 'start_time', 'end_time']

    def has_add_permission(self, request):
        return False