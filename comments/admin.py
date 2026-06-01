# -*- coding: utf-8 -*-
# @Author : Delock
# @Desc   : 评价模块后台管理 (兼容 Django 6+)

from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    ProductReview, ProductReviewItem, ProductReviewImage,
    ServiceReview, ServiceReviewImage,
    ReviewStatusMixin,
)


# ════════════════════════════════════════════════════════════
# 通用渲染工具
# ════════════════════════════════════════════════════════════
#
# 注意:Django 6+ 中 format_html 必须配合占位符使用,纯静态 HTML
# 一律使用 mark_safe,否则会抛 "args or kwargs must be provided"。
#
# ════════════════════════════════════════════════════════════

STATUS_BADGE_COLORS = {
    'pending':  '#FF9500',
    'approved': '#2BB673',
    'rejected': '#FF4D4F',
    'hidden':   '#8C8C8C',
}


def render_status_badge(status):
    """状态彩色 badge"""
    color = STATUS_BADGE_COLORS.get(status, '#999')
    label = dict(ReviewStatusMixin.Status.choices).get(status, status or '-')
    return format_html(
        '<span style="display:inline-block;padding:2px 10px;border-radius:10px;'
        'background:{};color:#fff;font-size:12px;line-height:1.5;font-weight:500;">{}</span>',
        color, label,
    )


def render_stars(score):
    """星级评分:★★★★★ 5"""
    if not score:
        return mark_safe('<span style="color:#bbb;">-</span>')
    score = int(score)
    full = '★' * score
    empty = '☆' * (5 - score)
    return format_html(
        '<span style="color:#FFB400;letter-spacing:2px;">{}{}</span>'
        '<span style="color:#999;margin-left:6px;font-size:11px;">{}</span>',
        full, empty, str(score),
    )


def render_thumb(url, size=42, radius=4):
    """单图缩略图"""
    if not url:
        return mark_safe('<span style="color:#bbb;">-</span>')
    return format_html(
        '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;'
        'border-radius:{}px;border:1px solid #eee;" />',
        url, size, size, radius,
    )


def render_thumbs(image_urls, max_count=3, size=48):
    """图片缩略图组"""
    if not image_urls:
        return mark_safe('<span style="color:#bbb;">-</span>')
    parts = []
    for url in image_urls[:max_count]:
        parts.append(format_html(
            '<img src="{}" style="width:{}px;height:{}px;object-fit:cover;'
            'border-radius:4px;margin-right:4px;border:1px solid #eee;vertical-align:middle;" />',
            url, size, size,
        ))
    if len(image_urls) > max_count:
        parts.append(format_html(
            '<span style="color:#999;font-size:12px;margin-left:4px;">+{}</span>',
            str(len(image_urls) - max_count),
        ))
    return mark_safe(''.join(str(p) for p in parts))


# ════════════════════════════════════════════════════════════
# 用户/订单/商品/服务 友好显示
# ════════════════════════════════════════════════════════════

def get_user_display(user):
    """根据真实 User 字段拼一个友好名,容错处理 username 为空"""
    if not user:
        return '-'
    name = user.username or ''
    phone = getattr(user, 'phone', '') or ''
    if name and phone:
        return f'{name} ({phone[-4:]})'
    if name:
        return name
    if phone:
        return f'用户{phone[-4:]}'
    return f'用户#{user.pk}'


def admin_url_safe(app_label, model_name, pk):
    """生成 admin change 页面 URL,reverse 失败返回 None"""
    try:
        return reverse(f'admin:{app_label}_{model_name}_change', args=[pk])
    except Exception:
        return None


# ════════════════════════════════════════════════════════════
# 商品评价图片 - Inline (整单)
# ════════════════════════════════════════════════════════════

class ProductReviewImageInline(admin.TabularInline):
    model = ProductReviewImage
    fk_name = 'review'
    extra = 0
    fields = ('preview', 'image', 'sort_order')
    readonly_fields = ('preview',)
    verbose_name = '整单图片'
    verbose_name_plural = '整单图片'

    def preview(self, obj):
        return render_thumb(obj.image if obj else None, size=72)
    preview.short_description = '预览'


# ════════════════════════════════════════════════════════════
# 商品评价图片 - Inline (单品)
# ════════════════════════════════════════════════════════════

class ProductReviewItemImageInline(admin.TabularInline):
    model = ProductReviewImage
    fk_name = 'review_item'
    extra = 0
    fields = ('preview', 'image', 'sort_order')
    readonly_fields = ('preview',)
    verbose_name = '商品图片'
    verbose_name_plural = '商品图片'

    def preview(self, obj):
        return render_thumb(obj.image if obj else None, size=72)
    preview.short_description = '预览'


# ════════════════════════════════════════════════════════════
# 商品评价明细 - Inline
# ════════════════════════════════════════════════════════════

class ProductReviewItemInline(admin.StackedInline):
    """商品维度评价 - 在商品评价详情页内联展示"""
    model = ProductReviewItem
    extra = 0
    fields = (
        'goods_image_preview',
        ('goods_title', 'sku_text'),
        ('score', 'quality_score', 'match_score'),
        'content',
        ('has_images', 'like_count'),
    )
    readonly_fields = (
        'goods_image_preview',
        'goods_title', 'sku_text',
        'has_images', 'like_count',
    )
    verbose_name = '商品评价明细'
    verbose_name_plural = '商品评价明细'
    can_delete = False
    show_change_link = True

    def goods_image_preview(self, obj):
        return render_thumb(obj.goods_image if obj else None, size=80)
    goods_image_preview.short_description = '商品图'

    def has_add_permission(self, request, obj=None):
        return False


# ════════════════════════════════════════════════════════════
# 共用的批量操作 Mixin
# ════════════════════════════════════════════════════════════

class _ReviewBulkActionsMixin:
    """批量审核 actions,商品评价 / 服务评价复用"""

    actions = ['action_approve', 'action_reject', 'action_hide', 'action_set_pending']

    def _bulk_set_status(self, request, queryset, target_status, label):
        updated = queryset.update(status=target_status, updated_at=timezone.now())
        self.message_user(
            request,
            f'已将 {updated} 条评价状态改为「{label}」',
            level=messages.SUCCESS,
        )

    def action_approve(self, request, queryset):
        self._bulk_set_status(request, queryset,
                              ReviewStatusMixin.Status.APPROVED, '已通过')
    action_approve.short_description = '✅ 批量审核通过'

    def action_reject(self, request, queryset):
        self._bulk_set_status(request, queryset,
                              ReviewStatusMixin.Status.REJECTED, '已拒绝')
    action_reject.short_description = '❌ 批量拒绝'

    def action_hide(self, request, queryset):
        self._bulk_set_status(request, queryset,
                              ReviewStatusMixin.Status.HIDDEN, '已隐藏')
    action_hide.short_description = '👁 批量隐藏'

    def action_set_pending(self, request, queryset):
        self._bulk_set_status(request, queryset,
                              ReviewStatusMixin.Status.PENDING, '待审核')
    action_set_pending.short_description = '↩ 重置为待审核'


# ════════════════════════════════════════════════════════════
# 商品评价
# ════════════════════════════════════════════════════════════

@admin.register(ProductReview)
class ProductReviewAdmin(_ReviewBulkActionsMixin, admin.ModelAdmin):
    list_display = (
        'id',
        'order_link',
        'user_link',
        'merchant_display',
        'logistics_score_display',
        'service_score_display',
        'avg_item_score_display',
        'content_short',
        'has_images_display',
        'is_anonymous',
        'status_badge',
        'replied_display',
        'created_at',
    )
    list_display_links = ('id', 'order_link')
    list_filter = (
        'status',
        'is_anonymous',
        'has_images',
        'logistics_score',
        'service_score',
        ('created_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'order__order_no',
        'merchant_name',
        'content',
        'replied_content',
        'user__username',
        'user__phone',
    )
    raw_id_fields = ('order', 'user')
    date_hierarchy = 'created_at'
    list_per_page = 30
    ordering = ('-created_at',)
    inlines = [ProductReviewImageInline, ProductReviewItemInline]

    fieldsets = (
        ('关联信息', {
            'fields': ('order', 'user', 'merchant_id', 'merchant_name'),
        }),
        ('评分', {
            'fields': ('logistics_score', 'service_score'),
        }),
        ('内容', {
            'fields': ('content', 'is_anonymous', 'has_images'),
        }),
        ('审核', {
            'fields': ('status',),
        }),
        ('商家回复', {
            'fields': ('replied_content', 'replied_at'),
        }),
        ('时间', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('has_images', 'created_at', 'updated_at')

    # ─── 列展示 ──────────────────────────────────────

    def order_link(self, obj):
        if not obj.order_id:
            return '-'
        order_no = obj.order.order_no if obj.order else f'#{obj.order_id}'
        url = admin_url_safe('bill', 'productorder', obj.order_id)
        if not url:
            return order_no
        return format_html('<a href="{}">{}</a>', url, order_no)
    order_link.short_description = '订单号'
    order_link.admin_order_field = 'order__order_no'

    def user_link(self, obj):
        if not obj.user_id:
            return '-'
        text = get_user_display(obj.user)
        url = admin_url_safe('user', 'user', obj.user_id)
        if not url:
            return text
        return format_html('<a href="{}">{}</a>', url, text)
    user_link.short_description = '用户'

    def merchant_display(self, obj):
        # merchant 在评价里只存了快照(merchant_id + merchant_name),没外键
        if obj.merchant_name:
            return format_html(
                '{}<br><span style="color:#999;font-size:11px;">ID:{}</span>',
                obj.merchant_name, str(obj.merchant_id),
            )
        return format_html('<span style="color:#999;">ID:{}</span>', str(obj.merchant_id))
    merchant_display.short_description = '商家'

    def logistics_score_display(self, obj):
        return render_stars(obj.logistics_score)
    logistics_score_display.short_description = '物流'

    def service_score_display(self, obj):
        return render_stars(obj.service_score)
    service_score_display.short_description = '服务'

    def avg_item_score_display(self, obj):
        avg = obj.avg_item_score
        if not avg:
            return mark_safe('<span style="color:#bbb;">-</span>')
        return format_html(
            '<span style="color:#FFB400;font-weight:bold;">{}</span>',
            f'{avg:.1f}',
        )
    avg_item_score_display.short_description = '商品均分'

    def content_short(self, obj):
        if not obj.content:
            return mark_safe('<span style="color:#bbb;">(无文字)</span>')
        s = obj.content[:30]
        if len(obj.content) > 30:
            s += '...'
        return s
    content_short.short_description = '评价内容'

    def has_images_display(self, obj):
        return '🖼' if obj.has_images else mark_safe('<span style="color:#bbb;">-</span>')
    has_images_display.short_description = '图'
    has_images_display.boolean = False

    def status_badge(self, obj):
        return render_status_badge(obj.status)
    status_badge.short_description = '状态'
    status_badge.admin_order_field = 'status'

    def replied_display(self, obj):
        if obj.replied_content:
            return mark_safe('<span style="color:#2BB673;">✓ 已回复</span>')
        return mark_safe('<span style="color:#bbb;">未回复</span>')
    replied_display.short_description = '商家回复'

    # ─── 性能优化 ────────────────────────────────────

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('order', 'user').prefetch_related('items', 'images')


# ════════════════════════════════════════════════════════════
# 商品评价明细 - 独立管理页(便于按商品/SKU筛选)
# ════════════════════════════════════════════════════════════

@admin.register(ProductReviewItem)
class ProductReviewItemAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'goods_thumb',
        'goods_link',
        'sku_text',
        'score_display',
        'quality_score_display',
        'match_score_display',
        'content_short',
        'has_images_display',
        'like_count',
        'review_status',
        'created_at',
    )
    list_display_links = ('id', 'goods_link')
    list_filter = (
        'score',
        'has_images',
        ('created_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'goods_title',
        'sku_text',
        'content',
        'review__order__order_no',
    )
    raw_id_fields = ('review', 'order_item', 'goods', 'sku')
    inlines = [ProductReviewItemImageInline]
    date_hierarchy = 'created_at'
    list_per_page = 30
    ordering = ('-created_at',)
    readonly_fields = ('has_images', 'like_count', 'created_at', 'updated_at')

    # ─── 列展示 ──────────────────────────────────────

    def goods_thumb(self, obj):
        return render_thumb(obj.goods_image, size=42)
    goods_thumb.short_description = '图'

    def goods_link(self, obj):
        title = obj.goods_title or '-'
        # 优先使用真实外键 goods,其次用快照 goods_id_snapshot
        gid = obj.goods_id or obj.goods_id_snapshot
        if not gid:
            return title
        url = admin_url_safe('product', 'goods', gid)
        if not url:
            return title
        return format_html('<a href="{}">{}</a>', url, title)
    goods_link.short_description = '商品'
    goods_link.admin_order_field = 'goods_title'

    def score_display(self, obj):
        return render_stars(obj.score)
    score_display.short_description = '总评'

    def quality_score_display(self, obj):
        return render_stars(obj.quality_score)
    quality_score_display.short_description = '质量'

    def match_score_display(self, obj):
        return render_stars(obj.match_score)
    match_score_display.short_description = '相符'

    def content_short(self, obj):
        if not obj.content:
            return mark_safe('<span style="color:#bbb;">(无文字)</span>')
        s = obj.content[:30]
        if len(obj.content) > 30:
            s += '...'
        return s
    content_short.short_description = '评价内容'

    def has_images_display(self, obj):
        return '🖼' if obj.has_images else mark_safe('<span style="color:#bbb;">-</span>')
    has_images_display.short_description = '图'

    def review_status(self, obj):
        if not obj.review:
            return '-'
        return render_status_badge(obj.review.status)
    review_status.short_description = '主评状态'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('review', 'goods', 'sku').prefetch_related('images')


# ════════════════════════════════════════════════════════════
# 服务评价图片 - Inline
# ════════════════════════════════════════════════════════════

class ServiceReviewImageInline(admin.TabularInline):
    model = ServiceReviewImage
    extra = 0
    fields = ('preview', 'image', 'sort_order')
    readonly_fields = ('preview',)
    verbose_name = '现场图片'
    verbose_name_plural = '现场图片'

    def preview(self, obj):
        return render_thumb(obj.image if obj else None, size=72)
    preview.short_description = '预览'


# ════════════════════════════════════════════════════════════
# 服务评价
# ════════════════════════════════════════════════════════════

@admin.register(ServiceReview)
class ServiceReviewAdmin(_ReviewBulkActionsMixin, admin.ModelAdmin):
    list_display = (
        'id',
        'order_link',
        'user_link',
        'service_thumb',
        'service_link',
        'merchant_display',
        'staff_display',
        'score_display',
        'attitude_score_display',
        'professional_score_display',
        'punctuality_score_display',
        'content_short',
        'has_images_display',
        'is_anonymous',
        'status_badge',
        'replied_display',
        'created_at',
    )
    list_display_links = ('id', 'order_link')
    list_filter = (
        'status',
        'is_anonymous',
        'has_images',
        'score',
        'attitude_score',
        'professional_score',
        'punctuality_score',
        ('created_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'order__order_no',
        'merchant_name',
        'service_name',
        'staff_name',
        'content',
        'replied_content',
        'user__username',
        'user__phone',
    )
    raw_id_fields = ('order', 'order_item', 'user', 'service')
    date_hierarchy = 'created_at'
    list_per_page = 30
    ordering = ('-created_at',)
    inlines = [ServiceReviewImageInline]

    fieldsets = (
        ('关联信息', {
            'fields': ('order', 'order_item', 'user', 'merchant_id', 'merchant_name'),
        }),
        ('服务快照', {
            'fields': (
                'service', 'service_id_snapshot', 'service_name',
                'service_image', 'spec_name',
            ),
        }),
        ('员工快照', {
            'fields': ('staff_id', 'staff_name'),
        }),
        ('服务时间快照', {
            'fields': ('service_start_at', 'service_end_at'),
        }),
        ('评分', {
            'fields': (
                'score', 'attitude_score', 'professional_score', 'punctuality_score',
            ),
        }),
        ('内容', {
            'fields': ('content', 'is_anonymous', 'has_images'),
        }),
        ('审核', {
            'fields': ('status',),
        }),
        ('商家回复', {
            'fields': ('replied_content', 'replied_at'),
        }),
        ('时间', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('has_images', 'created_at', 'updated_at')

    # ─── 列展示 ──────────────────────────────────────

    def order_link(self, obj):
        if not obj.order_id:
            return '-'
        order_no = obj.order.order_no if obj.order else f'#{obj.order_id}'
        url = admin_url_safe('bill', 'serviceorder', obj.order_id)
        if not url:
            return order_no
        return format_html('<a href="{}">{}</a>', url, order_no)
    order_link.short_description = '订单号'
    order_link.admin_order_field = 'order__order_no'

    def user_link(self, obj):
        if not obj.user_id:
            return '-'
        text = get_user_display(obj.user)
        url = admin_url_safe('user', 'user', obj.user_id)
        if not url:
            return text
        return format_html('<a href="{}">{}</a>', url, text)
    user_link.short_description = '用户'

    def merchant_display(self, obj):
        if obj.merchant_name:
            return format_html(
                '{}<br><span style="color:#999;font-size:11px;">ID:{}</span>',
                obj.merchant_name, str(obj.merchant_id),
            )
        return format_html('<span style="color:#999;">ID:{}</span>', str(obj.merchant_id))
    merchant_display.short_description = '商家'

    def service_thumb(self, obj):
        return render_thumb(obj.service_image, size=42)
    service_thumb.short_description = '图'

    def service_link(self, obj):
        name = obj.service_name or '-'
        sid = obj.service_id or obj.service_id_snapshot
        if not sid:
            return name
        url = admin_url_safe('services', 'service', sid)
        if not url:
            return name
        return format_html('<a href="{}">{}</a>', url, name)
    service_link.short_description = '服务'
    service_link.admin_order_field = 'service_name'

    def staff_display(self, obj):
        if obj.staff_name:
            sid = obj.staff_id
            if sid:
                url = admin_url_safe('staffs', 'staff', sid)
                if url:
                    return format_html(
                        '<a href="{}">{}</a><br><span style="color:#999;font-size:11px;">ID:{}</span>',
                        url, obj.staff_name, str(sid),
                    )
            return obj.staff_name
        return mark_safe('<span style="color:#bbb;">-</span>')
    staff_display.short_description = '员工'

    def score_display(self, obj):
        return render_stars(obj.score)
    score_display.short_description = '总评'

    def attitude_score_display(self, obj):
        return render_stars(obj.attitude_score)
    attitude_score_display.short_description = '态度'

    def professional_score_display(self, obj):
        return render_stars(obj.professional_score)
    professional_score_display.short_description = '专业'

    def punctuality_score_display(self, obj):
        return render_stars(obj.punctuality_score)
    punctuality_score_display.short_description = '准时'

    def content_short(self, obj):
        if not obj.content:
            return mark_safe('<span style="color:#bbb;">(无文字)</span>')
        s = obj.content[:30]
        if len(obj.content) > 30:
            s += '...'
        return s
    content_short.short_description = '评价内容'

    def has_images_display(self, obj):
        return '🖼' if obj.has_images else mark_safe('<span style="color:#bbb;">-</span>')
    has_images_display.short_description = '图'

    def status_badge(self, obj):
        return render_status_badge(obj.status)
    status_badge.short_description = '状态'
    status_badge.admin_order_field = 'status'

    def replied_display(self, obj):
        if obj.replied_content:
            return mark_safe('<span style="color:#2BB673;">✓ 已回复</span>')
        return mark_safe('<span style="color:#bbb;">未回复</span>')
    replied_display.short_description = '商家回复'

    # ─── 性能优化 ────────────────────────────────────

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('order', 'user', 'service').prefetch_related('images')


# ════════════════════════════════════════════════════════════
# (可选) 评价图片独立管理页
# 默认不注册;如果业务上需要单独搜索图片,把 @admin.register 解开即可
# ════════════════════════════════════════════════════════════

# @admin.register(ProductReviewImage)
# class ProductReviewImageAdmin(admin.ModelAdmin):
#     list_display = ('id', 'preview', 'review', 'review_item', 'sort_order', 'created_at')
#     raw_id_fields = ('review', 'review_item')
#     search_fields = ('image',)
#     ordering = ('-created_at',)
#
#     def preview(self, obj):
#         return render_thumb(obj.image, size=60)
#     preview.short_description = '预览'


# @admin.register(ServiceReviewImage)
# class ServiceReviewImageAdmin(admin.ModelAdmin):
#     list_display = ('id', 'preview', 'review', 'sort_order', 'created_at')
#     raw_id_fields = ('review',)
#     search_fields = ('image',)
#     ordering = ('-created_at',)
#
#     def preview(self, obj):
#         return render_thumb(obj.image, size=60)
#     preview.short_description = '预览'