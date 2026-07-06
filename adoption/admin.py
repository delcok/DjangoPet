# -*- coding: utf-8 -*-
"""
adoption/admin.py — 领养模块 Django Admin(适配 Django 5.1.2)

⚠️ 测试环境版本:已放开删除权限,用于清空测试数据。
   上线前请务必还原 has_delete_permission / has_add_permission,
   否则超管可在 Admin 里绕过 API 层直接物理删除业务数据。
"""
import json

from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from .models import (AdopterProfile, AdoptionApplication, AdoptionUpdate,
                     AdoptionUpdateTask, AdoptionViolation,
                     ApplicationStatusLog, PetFavorite, PetMedia, StrayPet)


# ============================================================
# 公共小工具
# ============================================================
def _badge(label, color):
    return format_html(
        '<span style="display:inline-block;padding:2px 10px;border-radius:10px;'
        'font-size:12px;color:#fff;background:{};white-space:nowrap;">{}</span>',
        color, label)


def _img_gallery(urls, height=56):
    if not urls:
        return '—'
    return format_html_join(
        '', '<img src="{}" style="height:{}px;margin:0 4px 4px 0;'
            'border-radius:4px;vertical-align:middle;"/>',
        ((u, height) for u in urls))


PET_STATUS_COLORS = {
    'draft': '#95a5a6', 'available': '#27ae60', 'full': '#e67e22',
    'handover': '#2980b9', 'adopted': '#8e44ad', 'paused': '#b8860b',
    'deceased': '#555555',
}
APP_STATUS_COLORS = {
    'submitted': '#95a5a6', 'reviewing': '#2980b9', 'interview': '#16a085',
    'approved': '#e67e22', 'completed': '#27ae60', 'rejected': '#c0392b',
    'cancelled': '#7f8c8d', 'expired': '#922b21', 'returned': '#a04000',
}
PROFILE_STATUS_COLORS = {'normal': '#27ae60', 'restricted': '#e67e22', 'banned': '#c0392b'}
TASK_STATUS_COLORS = {'pending': '#95a5a6', 'submitted': '#27ae60',
                      'overdue': '#c0392b', 'exempted': '#2980b9'}
REVIEW_STATUS_COLORS = {'pending': '#95a5a6', 'normal': '#27ae60', 'abnormal': '#c0392b'}


# ============================================================
# 1. 流浪宠物
# ============================================================
class PetMediaInline(admin.TabularInline):
    model = PetMedia
    extra = 1
    fields = ('media_type', 'url', 'sort_order', 'preview')
    readonly_fields = ('preview',)

    @admin.display(description='预览')
    def preview(self, obj):
        if not obj.pk or not obj.url:
            return '—'
        if obj.media_type == 'image':
            return format_html(
                '<img src="{}" style="height:60px;border-radius:4px;"/>', obj.url)
        return format_html('<a href="{}" target="_blank">▶ 查看视频</a>', obj.url)


@admin.register(StrayPet)
class StrayPetAdmin(admin.ModelAdmin):
    list_display = ('id', 'cover_thumb', 'name', 'species', 'breed', 'gender',
                    'age_text', 'city', 'status_badge', 'quota', 'view_count',
                    'favorite_count', 'sort_weight', 'is_deleted', 'created_at')
    list_display_links = ('id', 'name')
    list_editable = ('sort_weight',)
    list_filter = ('status', 'species', 'gender', 'size',
                   'is_sterilized', 'is_vaccinated', 'is_deleted', 'city')
    search_fields = ('name', 'breed', 'color', 'city', 'rescue_story')
    date_hierarchy = 'created_at'
    ordering = ('-sort_weight', '-created_at')
    list_per_page = 30
    empty_value_display = '—'
    inlines = [PetMediaInline]
    # 测试环境:新增物理删除动作
    actions = ['make_available', 'make_paused', 'hard_delete_pets']

    readonly_fields = ('applying_count', 'view_count', 'favorite_count',
                       'adopted_at', 'created_by', 'created_at', 'updated_at',
                       'cover_preview')

    fieldsets = (
        ('基本信息', {'fields': (('name', 'species', 'breed'),
                                 ('gender', 'size', 'weight_kg'),
                                 ('birth_date_est', 'age_text'), 'color')}),
        ('健康信息', {'fields': (('is_sterilized', 'is_vaccinated', 'is_dewormed'),
                                 'vaccine_detail', 'health_desc', 'special_needs')}),
        ('性格习性', {'fields': ('personality', ('good_with_kids', 'good_with_pets'))}),
        ('救助背景', {'fields': (('rescue_date', 'rescue_location'), 'rescue_story')}),
        ('位置信息', {'fields': (('province', 'city', 'district'), 'shelter_address')}),
        ('领养设置', {'fields': ('adoption_requirements',
                                 ('max_applying', 'applying_count'))}),
        ('运营与状态', {
            'description': '⚠️ full / handover / adopted 由申请流程自动流转,此处手改会被忽略;'
                           '上下架请在 draft / available / paused 之间切换。',
            'fields': (('status', 'sort_weight'),
                       ('cover_image', 'cover_preview'),
                       ('view_count', 'favorite_count', 'adopted_at'))}),
        ('系统信息', {'classes': ('collapse',),
                      'fields': (('created_by', 'is_deleted'),
                                 ('created_at', 'updated_at'))}),
    )

    # ---------- 展示列 ----------
    @admin.display(description='封面')
    def cover_thumb(self, obj):
        if obj.cover_image:
            return format_html(
                '<img src="{}" style="height:48px;width:48px;object-fit:cover;'
                'border-radius:6px;"/>', obj.cover_image)
        return '—'

    @admin.display(description='封面预览')
    def cover_preview(self, obj):
        if obj.cover_image:
            return format_html(
                '<img src="{}" style="max-height:200px;border-radius:8px;"/>',
                obj.cover_image)
        return '—'

    @admin.display(description='状态', ordering='status')
    def status_badge(self, obj):
        return _badge(obj.get_status_display(),
                      PET_STATUS_COLORS.get(obj.status, '#777'))

    @admin.display(description='名额', ordering='applying_count')
    def quota(self, obj):
        color = '#e67e22' if obj.applying_count >= obj.max_applying else '#27ae60'
        return format_html('<b style="color:{};">{} / {}</b>',
                           color, obj.applying_count, obj.max_applying)

    # ---------- 写保护 ----------
    def save_model(self, request, obj, form, change):
        if 'status' in form.changed_data and obj.status in ('full', 'handover', 'adopted'):
            obj.status = (type(obj).objects.get(pk=obj.pk).status
                          if change else 'draft')
            self.message_user(
                request, '⚠️ full/handover/adopted 由申请流程自动流转,本次状态修改已忽略',
                messages.WARNING)
        super().save_model(request, obj, form, change)

    # ---------- 删除权限(测试环境放开)----------
    def has_delete_permission(self, request, obj=None):
        return True

    # 单条删除:测试环境直接物理删除(连带申请等由级联/手动清理)
    def delete_model(self, request, obj):
        self._hard_delete(request, StrayPet.objects.filter(pk=obj.pk))

    def delete_queryset(self, request, queryset):
        self._hard_delete(request, queryset)

    def _hard_delete(self, request, queryset):
        """
        物理删除宠物。pet 被 AdoptionApplication 以 PROTECT 引用,
        必须先删申请及其下游数据,否则 ProtectedError。
        顺序:动态 → 打卡任务 → 日志 → 违规 → 申请 → 宠物。
        """
        pet_ids = list(queryset.values_list('id', flat=True))
        if not pet_ids:
            return
        apps = AdoptionApplication.objects.filter(pet_id__in=pet_ids)
        app_ids = list(apps.values_list('id', flat=True))

        AdoptionUpdate.objects.filter(application_id__in=app_ids).delete()
        AdoptionUpdateTask.objects.filter(application_id__in=app_ids).delete()
        ApplicationStatusLog.objects.filter(application_id__in=app_ids).delete()
        # 违规单 application 是 SET_NULL,这里连测试违规一起清掉
        AdoptionViolation.objects.filter(application_id__in=app_ids).delete()
        apps.delete()

        deleted, _ = queryset.delete()
        self.message_user(
            request,
            f'已物理删除 {len(pet_ids)} 只宠物及其 {len(app_ids)} 张申请和关联数据',
            messages.SUCCESS)

    # ---------- 批量动作 ----------
    @admin.action(description='批量上架(待上架/暂停 → 可领养)')
    def make_available(self, request, queryset):
        updated = queryset.filter(status__in=['draft', 'paused'],
                                  is_deleted=False).update(status='available')
        self.message_user(request, f'{updated} 只宠物已上架', messages.SUCCESS)

    @admin.action(description='批量暂停领养(可领养 → 暂停)')
    def make_paused(self, request, queryset):
        updated = queryset.filter(status='available').update(status='paused')
        self.message_user(request, f'{updated} 只宠物已暂停领养', messages.SUCCESS)

    @admin.action(description='⚠️ 物理删除选中宠物及全部关联数据(仅测试用)')
    def hard_delete_pets(self, request, queryset):
        self._hard_delete(request, queryset)


# ============================================================
# 2. 领养申请
# ============================================================
class ApplicationStatusLogInline(admin.TabularInline):
    model = ApplicationStatusLog
    extra = 0
    can_delete = True  # 测试环境允许删除内联日志
    fields = ('created_at', 'from_status', 'to_status', 'operator', 'remark')
    readonly_fields = fields
    verbose_name_plural = '状态流转日志'

    def has_add_permission(self, request, obj=None):
        return False


class AdoptionUpdateTaskInline(admin.TabularInline):
    model = AdoptionUpdateTask
    extra = 0
    can_delete = True
    fields = ('period_no', 'due_start', 'due_end', 'status',
              'remind_count', 'reminded_at')
    readonly_fields = fields
    verbose_name_plural = '打卡任务'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AdoptionApplication)
class AdoptionApplicationAdmin(admin.ModelAdmin):
    list_display = ('application_no', 'pet_link', 'real_name', 'masked_phone',
                    'housing_type', 'status_badge', 'review_score', 'created_at')
    list_filter = ('status', 'housing_type', 'has_experience',
                   ('created_at', admin.DateFieldListFilter))
    search_fields = ('application_no', 'real_name', 'phone', 'pet__name')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_per_page = 30
    list_select_related = ('pet', 'applicant')
    inlines = [ApplicationStatusLogInline, AdoptionUpdateTaskInline]
    empty_value_display = '—'

    readonly_fields = (
        'application_no', 'pet', 'applicant', 'status',
        'real_name', 'phone', 'wechat_id', 'age', 'occupation', 'address',
        'housing_type', 'landlord_allowed', 'family_agreed',
        'has_children', 'family_allergic',
        'has_experience', 'current_pets', 'monthly_budget',
        'accept_sterilization', 'accept_followup', 'accept_window_sealing',
        'reason', 'extra_answers_pretty', 'reviewer', 'reviewed_at',
        'reject_reason', 'approve_expire_at', 'handover_at',
        'agreement_url', 'update_plan', 'created_at', 'updated_at')

    fieldsets = (
        ('单据', {
            'description': '⚠️ 状态流转(审核/择优/交接/退养)必须走管理后台 API,'
                           '此处仅供查阅与补充内部备注。',
            'fields': (('application_no', 'status'),
                       ('pet', 'applicant'),
                       ('created_at', 'updated_at'))}),
        ('申请人快照', {'fields': (('real_name', 'phone', 'wechat_id'),
                                   ('age', 'occupation'), 'address')}),
        ('居住与家庭', {'fields': (('housing_type', 'landlord_allowed'),
                                   ('family_agreed', 'has_children', 'family_allergic'))}),
        ('经验与承诺', {'fields': (('has_experience', 'monthly_budget'),
                                   'current_pets',
                                   ('accept_sterilization', 'accept_followup',
                                    'accept_window_sealing'),
                                   'reason', 'extra_answers_pretty')}),
        ('审核信息', {'fields': (('review_score', 'reviewer', 'reviewed_at'),
                                 'review_note', 'reject_reason')}),
        ('交接与打卡计划', {'fields': (('approve_expire_at', 'handover_at'),
                                       'agreement_url', 'update_plan')}),
    )

    def has_add_permission(self, request):
        return False

    # 测试环境放开删除
    def has_delete_permission(self, request, obj=None):
        return True

    @admin.display(description='宠物', ordering='pet__name')
    def pet_link(self, obj):
        url = reverse('admin:adoption_straypet_change', args=[obj.pet_id])
        return format_html('<a href="{}">{}</a>', url, obj.pet.name)

    @admin.display(description='电话', ordering='phone')
    def masked_phone(self, obj):
        p = obj.phone or ''
        return f'{p[:3]}****{p[-4:]}' if len(p) >= 7 else p

    @admin.display(description='状态', ordering='status')
    def status_badge(self, obj):
        return _badge(obj.get_status_display(),
                      APP_STATUS_COLORS.get(obj.status, '#777'))

    @admin.display(description='扩展问卷答案')
    def extra_answers_pretty(self, obj):
        if not obj.extra_answers:
            return '—'
        return format_html(
            '<pre style="margin:0;white-space:pre-wrap;">{}</pre>',
            json.dumps(obj.extra_answers, ensure_ascii=False, indent=2))


# ============================================================
# 3. 状态日志
# ============================================================
@admin.register(ApplicationStatusLog)
class ApplicationStatusLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'application__application_no', 'flow',
                    'operator', 'remark', 'created_at')
    list_filter = ('to_status', ('created_at', admin.DateFieldListFilter))
    search_fields = ('application__application_no', 'remark')
    date_hierarchy = 'created_at'
    list_select_related = ('application', 'operator')
    list_per_page = 50

    @admin.display(description='流转')
    def flow(self, obj):
        return format_html('{} <b>→</b> {}', obj.from_status or '∅', obj.to_status)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # 测试环境放开删除
    def has_delete_permission(self, request, obj=None):
        return True


# ============================================================
# 4. 领养资格档案
# ============================================================
@admin.register(AdopterProfile)
class AdopterProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user__phone', 'status_badge', 'credit_score',
                    'applied_count', 'cancelled_count', 'adopted_count',
                    'returned_count', 'violation_count',
                    'restricted_until', 'updated_at')
    list_filter = ('status',)
    search_fields = ('user__phone', 'user__username')
    list_select_related = ('user',)
    show_facets = admin.ShowFacets.ALWAYS
    actions = ['lift_restriction', 'ban_users']
    raw_id_fields = ('user',)

    readonly_fields = ('user', 'applied_count', 'cancelled_count',
                       'adopted_count', 'returned_count', 'violation_count',
                       'created_at', 'updated_at')
    fields = ('user', ('status', 'restricted_until'), 'credit_score',
              ('applied_count', 'cancelled_count'),
              ('adopted_count', 'returned_count', 'violation_count'),
              'remark', ('created_at', 'updated_at'))

    def has_add_permission(self, request):
        return False

    # 测试环境放开删除
    def has_delete_permission(self, request, obj=None):
        return True

    @admin.display(description='资格状态', ordering='status')
    def status_badge(self, obj):
        return _badge(obj.get_status_display(),
                      PROFILE_STATUS_COLORS.get(obj.status, '#777'))

    @admin.action(description='解除限制(恢复正常)')
    def lift_restriction(self, request, queryset):
        updated = queryset.exclude(status='normal').update(
            status='normal', restricted_until=None)
        self.message_user(request, f'{updated} 个用户已恢复领养资格', messages.SUCCESS)

    @admin.action(description='永久禁止领养(请先确认已有违规记录留痕)')
    def ban_users(self, request, queryset):
        updated = queryset.update(status='banned', restricted_until=None)
        self.message_user(request, f'{updated} 个用户已被永久禁止领养', messages.SUCCESS)


# ============================================================
# 5. 违规记录
# ============================================================
@admin.register(AdoptionViolation)
class AdoptionViolationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user__phone', 'violation_type', 'penalty_badge',
                    'credit_deduct', 'restrict_days', 'is_system',
                    'application__application_no', 'created_at')
    list_filter = ('violation_type', 'penalty', 'is_system',
                   ('created_at', admin.DateFieldListFilter))
    search_fields = ('user__phone', 'description',
                     'application__application_no')
    date_hierarchy = 'created_at'
    list_select_related = ('user', 'application', 'operator')
    readonly_fields = ('user', 'application', 'violation_type', 'penalty',
                       'restrict_days', 'credit_deduct', 'description',
                       'evidence_preview', 'is_system', 'operator', 'created_at')
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # 测试环境放开删除
    def has_delete_permission(self, request, obj=None):
        return True

    @admin.display(description='处罚', ordering='penalty')
    def penalty_badge(self, obj):
        colors = {'warning': '#e67e22', 'restrict': '#c0392b', 'ban': '#641e16'}
        return _badge(obj.get_penalty_display(), colors.get(obj.penalty, '#777'))

    @admin.display(description='证据图片')
    def evidence_preview(self, obj):
        return _img_gallery(obj.evidence_images, height=80)


# ============================================================
# 6. 打卡任务
# ============================================================
@admin.register(AdoptionUpdateTask)
class AdoptionUpdateTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'application__application_no', 'pet_name',
                    'period_no', 'due_start', 'due_end', 'status_badge',
                    'remind_count', 'reminded_at')
    list_filter = ('status', 'period_no')
    search_fields = ('application__application_no',
                     'application__real_name', 'application__pet__name')
    date_hierarchy = 'due_end'
    ordering = ('due_end',)
    list_select_related = ('application', 'application__pet')
    actions = ['exempt_tasks']

    readonly_fields = ('application', 'period_no', 'due_start', 'due_end',
                       'status', 'reminded_at', 'remind_count',
                       'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    # 测试环境放开删除
    def has_delete_permission(self, request, obj=None):
        return True

    @admin.display(description='宠物', ordering='application__pet__name')
    def pet_name(self, obj):
        return obj.application.pet.name

    @admin.display(description='状态', ordering='status')
    def status_badge(self, obj):
        return _badge(obj.get_status_display(),
                      TASK_STATUS_COLORS.get(obj.status, '#777'))

    @admin.action(description='豁免选中任务(特殊情况免打卡)')
    def exempt_tasks(self, request, queryset):
        updated = queryset.filter(status__in=['pending', 'overdue']).update(
            status='exempted', updated_at=timezone.now())
        self.message_user(request, f'{updated} 期打卡任务已豁免', messages.SUCCESS)


# ============================================================
# 7. 领养动态
# ============================================================
@admin.register(AdoptionUpdate)
class AdoptionUpdateAdmin(admin.ModelAdmin):
    list_display = ('id', 'application__application_no', 'pet_name', 'source',
                    'period', 'images_count', 'is_public',
                    'review_badge', 'created_at')
    list_filter = ('review_status', 'source', 'is_public',
                   ('created_at', admin.DateFieldListFilter))
    search_fields = ('application__application_no', 'content',
                     'application__pet__name')
    date_hierarchy = 'created_at'
    list_select_related = ('application', 'application__pet', 'task')
    actions = ['mark_normal', 'mark_abnormal']

    readonly_fields = ('application', 'task', 'source', 'content',
                       'images_preview', 'video_url', 'related_post_id',
                       'reviewed_by', 'reviewed_at', 'created_at')
    fields = (('application', 'task', 'source'), 'content', 'images_preview',
              'video_url', 'related_post_id',
              ('is_public', 'review_status'),
              ('reviewed_by', 'reviewed_at'), 'created_at')

    def has_add_permission(self, request):
        return False

    # 测试环境放开删除
    def has_delete_permission(self, request, obj=None):
        return True

    @admin.display(description='宠物', ordering='application__pet__name')
    def pet_name(self, obj):
        return obj.application.pet.name

    @admin.display(description='期数')
    def period(self, obj):
        return obj.task.period_no if obj.task_id else '加更'

    @admin.display(description='图片数')
    def images_count(self, obj):
        return len(obj.images or [])

    @admin.display(description='结论', ordering='review_status')
    def review_badge(self, obj):
        return _badge(obj.get_review_status_display(),
                      REVIEW_STATUS_COLORS.get(obj.review_status, '#777'))

    @admin.display(description='图片预览')
    def images_preview(self, obj):
        return _img_gallery(obj.images, height=90)

    @admin.action(description='批量标记: 状态良好')
    def mark_normal(self, request, queryset):
        updated = queryset.update(review_status='normal',
                                  reviewed_at=timezone.now())
        self.message_user(request, f'{updated} 条动态已标记为状态良好',
                          messages.SUCCESS)

    @admin.action(description='批量标记: 存在异常(后续处罚请走违规接口)')
    def mark_abnormal(self, request, queryset):
        updated = queryset.update(review_status='abnormal',
                                  reviewed_at=timezone.now())
        self.message_user(request, f'{updated} 条动态已标记为异常,请跟进处理',
                          messages.WARNING)


# ============================================================
# 8. 收藏
# ============================================================
@admin.register(PetFavorite)
class PetFavoriteAdmin(admin.ModelAdmin):
    list_display = ('id', 'user__phone', 'pet_name', 'created_at')
    search_fields = ('user__phone', 'pet__name')
    date_hierarchy = 'created_at'
    list_select_related = ('user', 'pet')

    @admin.display(description='宠物', ordering='pet__name')
    def pet_name(self, obj):
        return obj.pet.name

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    # 测试环境放开删除
    def has_delete_permission(self, request, obj=None):
        return True