# -*- coding: utf-8 -*-
"""
adoption/serializers.py — 领养模块序列化器

无 service 层架构约定:
- 写操作的状态机/事务/行锁逻辑收敛在各 Serializer 的 create()/save() 内
- 异步通知一律 transaction.on_commit 后投递 Celery
  (按任务名 send_task 投递: 与 tasks.py 解耦,不会循环导入,tasks 未注册也不报 ImportError)
- 定时扫描(逾期交接/逾期打卡/限制到期)在 tasks.py 的 celery beat 任务里
"""
from datetime import timedelta

from celery import current_app
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers

from .models import (
    AdopterProfile, AdoptionApplication, AdoptionUpdate, AdoptionUpdateTask,
    AdoptionViolation, ApplicationStatusLog, PetFavorite, PetMedia, StrayPet,
)

# ---------- 业务常量 ----------
APPROVE_HANDOVER_DAYS = 7        # 审核通过后 N 天内须完成交接,逾期由 celery 扫成 expired
UPDATE_WINDOW_DAYS = 3           # 打卡窗口: 计划日前后各 N 天
LOSER_REJECT_REASON = '本次未能匹配成功,感谢您的爱心'

STATUS_DISPLAY_MAP = dict(AdoptionApplication.STATUS_CHOICES)


def dispatch_task(task_path, *args, **kwargs):
    """事务提交成功后再投递 Celery 任务(失败回滚则不发,避免幽灵通知)"""
    transaction.on_commit(lambda: current_app.send_task(task_path, args=args, kwargs=kwargs))


def mask_phone(phone):
    if phone and len(phone) >= 7:
        return f'{phone[:3]}****{phone[-4:]}'
    return phone


def log_status(application, from_status, to_status, operator=None, remark=''):
    ApplicationStatusLog.objects.create(
        application=application, from_status=from_status,
        to_status=to_status, operator=operator, remark=remark,
    )


# ============================================================
# 宠物侧
# ============================================================
class PetMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PetMedia
        fields = ['id', 'pet', 'media_type', 'url', 'sort_order']
        extra_kwargs = {'pet': {'write_only': True}}


class PetBriefSerializer(serializers.ModelSerializer):
    """嵌套在申请单/收藏里的宠物卡片"""
    species_display = serializers.CharField(source='get_species_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = StrayPet
        fields = ['id', 'name', 'species', 'species_display', 'breed',
                  'cover_image', 'city', 'status', 'status_display']


class StrayPetListSerializer(serializers.ModelSerializer):
    """C端列表页卡片"""
    species_display = serializers.CharField(source='get_species_display', read_only=True)
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    remaining_quota = serializers.SerializerMethodField()
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = StrayPet
        fields = ['id', 'name', 'species', 'species_display', 'breed',
                  'gender', 'gender_display', 'age_text', 'size', 'city', 'district',
                  'cover_image', 'is_sterilized', 'is_vaccinated',
                  'status', 'status_display', 'applying_count', 'max_applying',
                  'remaining_quota', 'favorite_count', 'view_count',
                  'is_favorited', 'created_at']

    def get_remaining_quota(self, obj):
        return max(obj.max_applying - obj.applying_count, 0)

    def get_is_favorited(self, obj):
        # 视图一次性查出当前用户收藏的 pet_id 集合放入 context,避免 N+1
        fav_ids = self.context.get('favorited_pet_ids')
        return obj.id in fav_ids if fav_ids is not None else False


class StrayPetDetailSerializer(StrayPetListSerializer):
    """C端详情页(不暴露 shelter_address / created_by 等内部字段)"""
    media = PetMediaSerializer(many=True, read_only=True)
    my_application = serializers.SerializerMethodField()

    class Meta(StrayPetListSerializer.Meta):
        fields = StrayPetListSerializer.Meta.fields + [
            'weight_kg', 'color', 'is_dewormed', 'vaccine_detail',
            'health_desc', 'special_needs', 'personality',
            'good_with_kids', 'good_with_pets',
            'rescue_date', 'rescue_location', 'rescue_story',
            'province', 'adoption_requirements', 'adopted_at', 'media',
            'my_application',
        ]

    def get_my_application(self, obj):
        """当前用户对这只宠物的进行中申请(视图查好放 context)"""
        app = self.context.get('my_application')
        if app:
            return {
                'id': app.id,
                'application_no': app.application_no,
                'status': app.status,
                'status_display': app.get_status_display(),
            }
        return None


class StrayPetAdminSerializer(serializers.ModelSerializer):
    """后台管理员对宠物的完整读写"""
    media = PetMediaSerializer(many=True, read_only=True)
    species_display = serializers.CharField(source='get_species_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    # 申请流程自动流转的状态,禁止后台手填
    AUTO_ONLY_STATUSES = {'full', 'handover', 'adopted'}

    class Meta:
        model = StrayPet
        fields = ['id', 'name', 'species', 'species_display', 'breed', 'gender',
                  'birth_date_est', 'age_text', 'size', 'weight_kg', 'color',
                  'is_sterilized', 'is_vaccinated', 'vaccine_detail', 'is_dewormed',
                  'health_desc', 'special_needs', 'personality',
                  'good_with_kids', 'good_with_pets',
                  'rescue_date', 'rescue_location', 'rescue_story',
                  'province', 'city', 'district', 'shelter_address',
                  'adoption_requirements', 'max_applying', 'applying_count',
                  'status', 'status_display', 'cover_image',
                  'view_count', 'favorite_count', 'sort_weight',
                  'adopted_at', 'created_by', 'created_at', 'updated_at', 'media']
        read_only_fields = ['applying_count', 'view_count', 'favorite_count',
                            'adopted_at', 'created_by', 'created_at', 'updated_at']

    def validate_status(self, value):
        if value in self.AUTO_ONLY_STATUSES and (
                self.instance is None or self.instance.status != value):
            raise serializers.ValidationError('该状态由申请流程自动流转,请勿手动设置')
        return value

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user  # Manager
        return super().create(validated_data)


# ============================================================
# 申请单 — C端
# ============================================================
class ApplicationStatusLogPublicSerializer(serializers.ModelSerializer):
    """给用户看的状态时间线(不暴露内部备注与操作人)"""
    to_status_display = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationStatusLog
        fields = ['from_status', 'to_status', 'to_status_display', 'created_at']

    def get_to_status_display(self, obj):
        return STATUS_DISPLAY_MAP.get(obj.to_status, obj.to_status)


class AdoptionUpdateTaskSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AdoptionUpdateTask
        fields = ['id', 'period_no', 'due_start', 'due_end',
                  'status', 'status_display']


class AdoptionUpdateTaskDetailSerializer(AdoptionUpdateTaskSerializer):
    """带宠物/申请上下文的任务(C端"我的打卡任务"页 + 后台逾期看板共用)"""
    application_no = serializers.CharField(source='application.application_no', read_only=True)
    pet = PetBriefSerializer(source='application.pet', read_only=True)

    class Meta(AdoptionUpdateTaskSerializer.Meta):
        fields = AdoptionUpdateTaskSerializer.Meta.fields + [
            'application', 'application_no', 'pet']


class AdoptionApplicationCreateSerializer(serializers.ModelSerializer):
    """
    用户提交领养申请。
    核心逻辑全在这里(无 service 层):
    资格校验 → 行锁宠物复核名额 → 创建申请 → 计数/状态联动 → 写日志 → on_commit 投递通知
    """
    pet = serializers.PrimaryKeyRelatedField(
        queryset=StrayPet.objects.filter(is_deleted=False))

    class Meta:
        model = AdoptionApplication
        fields = ['id', 'application_no', 'status', 'pet',
                  'real_name', 'phone', 'wechat_id', 'age', 'occupation', 'address',
                  'housing_type', 'landlord_allowed', 'family_agreed',
                  'has_children', 'family_allergic',
                  'has_experience', 'current_pets', 'monthly_budget',
                  'accept_sterilization', 'accept_followup', 'accept_window_sealing',
                  'reason', 'extra_answers', 'created_at']
        read_only_fields = ['id', 'application_no', 'status', 'created_at']
        extra_kwargs = {
            'phone': {'required': False},  # 缺省回填 user.phone
        }

    def validate(self, attrs):
        user = self.context['request'].user
        pet = attrs['pet']

        # 1. 领养资格(首次申请时建档)
        profile, _ = AdopterProfile.objects.get_or_create(user=user)
        if not profile.can_apply:
            raise serializers.ValidationError('您的领养资格当前受限,如有疑问请联系客服')

        # 2. 宠物可申请(粗校验,create 内还会行锁复核)
        if not pet.can_accept_application:
            raise serializers.ValidationError('该宠物当前不可申请(名额已满或状态变更)')

        # 3. 表单业务规则
        if attrs.get('housing_type') == 'rent' and attrs.get('landlord_allowed') is None:
            raise serializers.ValidationError(
                {'landlord_allowed': '租房用户请确认房东是否允许养宠'})
        if not attrs.get('family_agreed'):
            raise serializers.ValidationError(
                {'family_agreed': '需家庭成员一致同意方可申请'})
        if not attrs.get('accept_followup'):
            raise serializers.ValidationError(
                {'accept_followup': '需同意定期回访打卡方可申请'})
        if pet.species == 'cat' and attrs.get('accept_window_sealing') is not True:
            raise serializers.ValidationError(
                {'accept_window_sealing': '领养猫咪需承诺封窗'})

        # 4. 重复申请友好拦截(数据库条件唯一约束兜底并发)
        if AdoptionApplication.objects.filter(
                pet=pet, applicant=user,
                status__in=AdoptionApplication.ACTIVE_STATUSES).exists():
            raise serializers.ValidationError('您已提交过该宠物的申请,请勿重复提交')

        self._profile = profile
        return attrs

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data.setdefault('phone', user.phone)
        pet = validated_data.pop('pet')

        try:
            with transaction.atomic():
                # 行锁防止并发把名额打超
                locked_pet = StrayPet.objects.select_for_update().get(pk=pet.pk)
                if not locked_pet.can_accept_application:
                    raise serializers.ValidationError('手慢了,该宠物的申请名额刚刚满了')

                application = AdoptionApplication.objects.create(
                    applicant=user, pet=locked_pet, **validated_data)

                locked_pet.applying_count += 1
                if locked_pet.applying_count >= locked_pet.max_applying:
                    locked_pet.status = 'full'
                locked_pet.save(update_fields=['applying_count', 'status', 'updated_at'])

                log_status(application, '', 'submitted', remark='用户提交申请')
                AdopterProfile.objects.filter(pk=self._profile.pk).update(
                    applied_count=F('applied_count') + 1)
        except IntegrityError:
            # 并发下撞条件唯一约束
            raise serializers.ValidationError('您已提交过该宠物的申请,请勿重复提交')

        dispatch_task('adoption.tasks.notify_new_application', application.id)
        return application


class MyApplicationListSerializer(serializers.ModelSerializer):
    pet = PetBriefSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AdoptionApplication
        fields = ['id', 'application_no', 'pet', 'status', 'status_display',
                  'reject_reason', 'created_at']


class MyApplicationDetailSerializer(MyApplicationListSerializer):
    status_logs = ApplicationStatusLogPublicSerializer(many=True, read_only=True)
    update_tasks = AdoptionUpdateTaskSerializer(many=True, read_only=True)

    class Meta(MyApplicationListSerializer.Meta):
        fields = MyApplicationListSerializer.Meta.fields + [
            'real_name', 'phone', 'wechat_id', 'age', 'occupation', 'address',
            'housing_type', 'landlord_allowed', 'family_agreed',
            'has_children', 'family_allergic',
            'has_experience', 'current_pets', 'monthly_budget',
            'accept_sterilization', 'accept_followup', 'accept_window_sealing',
            'reason', 'extra_answers',
            'approve_expire_at', 'handover_at', 'agreement_url', 'update_plan',
            'status_logs', 'update_tasks',
        ]


class ApplicationCancelSerializer(serializers.Serializer):
    """用户自助取消。approved(待交接)不可自助取消,防止钻爽约空子,需联系工作人员。"""
    CANCELLABLE = ('submitted', 'reviewing', 'interview')

    reason = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate(self, attrs):
        app = self.context['application']
        if app.status not in self.CANCELLABLE:
            if app.status == 'approved':
                raise serializers.ValidationError('申请已通过待交接,如需取消请联系工作人员')
            raise serializers.ValidationError('当前状态不可取消')
        return attrs

    def save(self, **kwargs):
        app = self.context['application']
        reason = self.validated_data.get('reason', '')

        with transaction.atomic():
            app = AdoptionApplication.objects.select_for_update().get(pk=app.pk)
            if app.status not in self.CANCELLABLE:
                raise serializers.ValidationError('当前状态不可取消')
            pet = StrayPet.objects.select_for_update().get(pk=app.pet_id)

            old_status = app.status
            app.status = 'cancelled'
            app.save(update_fields=['status', 'updated_at'])

            # 释放名额
            pet.applying_count = max(pet.applying_count - 1, 0)
            if pet.status == 'full' and pet.applying_count < pet.max_applying:
                pet.status = 'available'
            pet.save(update_fields=['applying_count', 'status', 'updated_at'])

            log_status(app, old_status, 'cancelled', remark=reason or '用户自助取消')
            AdopterProfile.objects.filter(user_id=app.applicant_id).update(
                cancelled_count=F('cancelled_count') + 1)

        dispatch_task('adoption.tasks.notify_application_cancelled', app.id)
        return app


# ============================================================
# 申请单 — 后台(管理员审核 + 择优)
# ============================================================
class ApplicationStatusLogAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApplicationStatusLog
        fields = ['from_status', 'to_status', 'operator', 'remark', 'created_at']


class ApplicationAdminListSerializer(serializers.ModelSerializer):
    """后台列表: 同一宠物的几张申请放在一起对比择优"""
    pet = PetBriefSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    housing_type_display = serializers.CharField(source='get_housing_type_display', read_only=True)
    applicant_profile = serializers.SerializerMethodField()

    class Meta:
        model = AdoptionApplication
        fields = ['id', 'application_no', 'pet', 'applicant',
                  'real_name', 'phone', 'wechat_id',
                  'housing_type', 'housing_type_display', 'has_experience',
                  'status', 'status_display', 'review_score',
                  'applicant_profile', 'created_at']

    def get_applicant_profile(self, obj):
        """择优参考: 申请人的领养信用画像(视图 select_related('applicant__adopter_profile'))"""
        profile = getattr(obj.applicant, 'adopter_profile', None)
        if profile is None:
            return None
        return {
            'status': profile.status,
            'credit_score': profile.credit_score,
            'adopted_count': profile.adopted_count,
            'cancelled_count': profile.cancelled_count,
            'returned_count': profile.returned_count,
            'violation_count': profile.violation_count,
        }


class ApplicationAdminDetailSerializer(ApplicationAdminListSerializer):
    status_logs = ApplicationStatusLogAdminSerializer(many=True, read_only=True)
    update_tasks = AdoptionUpdateTaskSerializer(many=True, read_only=True)

    class Meta(ApplicationAdminListSerializer.Meta):
        fields = ApplicationAdminListSerializer.Meta.fields + [
            'age', 'occupation', 'address', 'landlord_allowed', 'family_agreed',
            'has_children', 'family_allergic', 'current_pets', 'monthly_budget',
            'accept_sterilization', 'accept_followup', 'accept_window_sealing',
            'reason', 'extra_answers',
            'reviewer', 'reviewed_at', 'review_note', 'reject_reason',
            'approve_expire_at', 'handover_at', 'agreement_url', 'update_plan',
            'status_logs', 'update_tasks',
        ]


class ApplicationAdminActionSerializer(serializers.Serializer):
    """
    管理员对申请单的所有流转动作,一个接口收口。
    择优核心: approve 时同宠物其余进行中申请被系统批量拒绝。
    视图用法: serializer = ApplicationAdminActionSerializer(
                  data=request.data,
                  context={'request': request, 'application': application})
    """
    ACTION_CHOICES = ['start_review', 'to_interview', 'approve',
                      'reject', 'complete', 'returned']

    # action: (允许的来源状态集合, 目标状态)
    TRANSITIONS = {
        'start_review': ({'submitted'}, 'reviewing'),
        'to_interview': ({'reviewing'}, 'interview'),
        'approve':      ({'reviewing', 'interview'}, 'approved'),
        'reject':       ({'submitted', 'reviewing', 'interview'}, 'rejected'),
        'complete':     ({'approved'}, 'completed'),
        'returned':     ({'completed'}, 'returned'),
    }

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    review_score = serializers.IntegerField(required=False, min_value=0, max_value=100)
    review_note = serializers.CharField(required=False, allow_blank=True)
    reject_reason = serializers.CharField(required=False, allow_blank=True, max_length=200)
    agreement_url = serializers.URLField(required=False, allow_blank=True, max_length=500)
    remark = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate(self, attrs):
        app = self.context['application']
        action = attrs['action']
        allowed_from, _ = self.TRANSITIONS[action]
        if app.status not in allowed_from:
            raise serializers.ValidationError(
                f'当前状态 [{app.get_status_display()}] 不能执行 [{action}]')
        if action == 'reject' and not attrs.get('reject_reason'):
            raise serializers.ValidationError({'reject_reason': '拒绝必须填写原因(将展示给用户)'})
        return attrs

    def save(self, **kwargs):
        manager = self.context['request'].user
        action = self.validated_data['action']
        _, to_status = self.TRANSITIONS[action]
        now = timezone.now()

        with transaction.atomic():
            app = AdoptionApplication.objects.select_for_update().get(
                pk=self.context['application'].pk)
            allowed_from, _ = self.TRANSITIONS[action]
            if app.status not in allowed_from:
                raise serializers.ValidationError('状态已变更,请刷新后重试')
            pet = StrayPet.objects.select_for_update().get(pk=app.pet_id)

            old_status = app.status
            app.status = to_status
            app.reviewer = manager
            app.reviewed_at = now
            if 'review_score' in self.validated_data:
                app.review_score = self.validated_data['review_score']
            if self.validated_data.get('review_note'):
                app.review_note = self.validated_data['review_note']

            if action == 'approve':
                app.approve_expire_at = now + timedelta(days=APPROVE_HANDOVER_DAYS)
                # —— 择优: 批量拒绝同宠物其余进行中申请 ——
                siblings = (AdoptionApplication.objects.select_for_update()
                            .filter(pet_id=pet.id,
                                    status__in=AdoptionApplication.ACTIVE_STATUSES)
                            .exclude(pk=app.pk))
                for sib in siblings:
                    sib_old = sib.status
                    sib.status = 'rejected'
                    sib.reject_reason = LOSER_REJECT_REASON
                    sib.reviewed_at = now
                    sib.save(update_fields=['status', 'reject_reason',
                                            'reviewed_at', 'updated_at'])
                    log_status(sib, sib_old, 'rejected', operator=manager,
                               remark='择优落选,系统自动拒绝')
                    dispatch_task('adoption.tasks.notify_application_result', sib.id)
                pet.status = 'handover'
                pet.applying_count = 1  # 仅剩通过的这张占名额

            elif action == 'reject':
                app.reject_reason = self.validated_data['reject_reason']
                pet.applying_count = max(pet.applying_count - 1, 0)
                if pet.status == 'full' and pet.applying_count < pet.max_applying:
                    pet.status = 'available'

            elif action == 'complete':
                app.handover_at = now
                if self.validated_data.get('agreement_url'):
                    app.agreement_url = self.validated_data['agreement_url']
                pet.status = 'adopted'
                pet.adopted_at = now
                pet.applying_count = 0
                AdopterProfile.objects.filter(user_id=app.applicant_id).update(
                    adopted_count=F('adopted_count') + 1)
                self._generate_update_tasks(app, base_time=now)

            elif action == 'returned':
                # 退养: 宠物先 paused 观察,后台确认健康后再手动上架
                pet.status = 'paused'
                pet.applying_count = 0
                AdopterProfile.objects.filter(user_id=app.applicant_id).update(
                    returned_count=F('returned_count') + 1)
                # 是否构成违规(弃养)由管理员另走违规接口判定

            app.save()
            pet.save(update_fields=['status', 'applying_count',
                                    'adopted_at', 'updated_at'])
            log_status(app, old_status, to_status, operator=manager,
                       remark=self.validated_data.get('remark', ''))

        dispatch_task('adoption.tasks.notify_application_result', app.id)
        return app

    @staticmethod
    def _generate_update_tasks(application, base_time):
        """交接完成时按 update_plan 批量生成打卡任务"""
        plan = application.update_plan or []
        window = timedelta(days=UPDATE_WINDOW_DAYS)
        tasks = []
        for period_no, days in enumerate(sorted({int(d) for d in plan}), start=1):
            due = base_time + timedelta(days=days)
            tasks.append(AdoptionUpdateTask(
                application=application, period_no=period_no,
                due_start=due - window, due_end=due + window))
        AdoptionUpdateTask.objects.bulk_create(tasks)


# ============================================================
# 领养后动态(打卡)
# ============================================================
class AdoptionUpdateCreateSerializer(serializers.ModelSerializer):
    """领养人提交打卡(关联任务)或自主加更(task 为空)"""
    application = serializers.PrimaryKeyRelatedField(
        queryset=AdoptionApplication.objects.filter(status='completed'))
    task = serializers.PrimaryKeyRelatedField(
        queryset=AdoptionUpdateTask.objects.all(), required=False, allow_null=True)
    images = serializers.ListField(
        child=serializers.URLField(max_length=500), min_length=1, max_length=9,
        help_text='打卡至少1张照片佐证')

    class Meta:
        model = AdoptionUpdate
        fields = ['id', 'application', 'task', 'content', 'images',
                  'video_url', 'is_public', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        user = self.context['request'].user
        app = attrs['application']
        if app.applicant_id != user.id:
            raise serializers.ValidationError('只能为自己的领养记录打卡')

        task = attrs.get('task')
        if task:
            if task.application_id != app.id:
                raise serializers.ValidationError({'task': '打卡任务与申请单不匹配'})
            if task.status in ('submitted', 'exempted'):
                raise serializers.ValidationError({'task': '该期打卡已完成,无需重复提交'})
        return attrs

    def create(self, validated_data):
        with transaction.atomic():
            update = AdoptionUpdate.objects.create(source='user', **validated_data)
            task = validated_data.get('task')
            if task:
                # 逾期后补卡同样置为 submitted(逾期违规由定时任务在逾期时已处理)
                AdoptionUpdateTask.objects.filter(pk=task.pk).update(
                    status='submitted', updated_at=timezone.now())
        dispatch_task('adoption.tasks.notify_update_submitted', update.id)
        return update


class AdoptionUpdatePublicSerializer(serializers.ModelSerializer):
    """宠物详情页"领养后的TA"公开动态流(视图过滤 is_public=True 且非 abnormal)"""
    period_no = serializers.SerializerMethodField()
    adopter_name = serializers.SerializerMethodField()

    class Meta:
        model = AdoptionUpdate
        fields = ['id', 'content', 'images', 'video_url',
                  'period_no', 'adopter_name', 'created_at']

    def get_period_no(self, obj):
        return obj.task.period_no if obj.task_id else None

    def get_adopter_name(self, obj):
        user = obj.application.applicant
        return getattr(user, 'display_name', None) or '爱心领养人'


class AdoptionUpdateAdminSerializer(serializers.ModelSerializer):
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    review_status_display = serializers.CharField(source='get_review_status_display', read_only=True)
    period_no = serializers.SerializerMethodField()

    class Meta:
        model = AdoptionUpdate
        fields = ['id', 'application', 'task', 'period_no', 'source', 'source_display',
                  'content', 'images', 'video_url', 'related_post_id', 'is_public',
                  'review_status', 'review_status_display',
                  'reviewed_by', 'reviewed_at', 'created_at']

    def get_period_no(self, obj):
        return obj.task.period_no if obj.task_id else None


class AdoptionUpdateReviewSerializer(serializers.Serializer):
    """管理员查看打卡内容并给出结论;abnormal 触发告警,后续处罚走违规接口"""
    review_status = serializers.ChoiceField(choices=['normal', 'abnormal'])

    def save(self, **kwargs):
        manager = self.context['request'].user
        update = self.context['update']
        update.review_status = self.validated_data['review_status']
        update.reviewed_by = manager
        update.reviewed_at = timezone.now()
        update.save(update_fields=['review_status', 'reviewed_by', 'reviewed_at'])
        if update.review_status == 'abnormal':
            dispatch_task('adoption.tasks.alert_abnormal_update', update.id)
        return update


class AdoptionUpdateStaffCreateSerializer(serializers.ModelSerializer):
    """后台回访代录(管理员电话/上门核实后录入,source='staff')"""
    application = serializers.PrimaryKeyRelatedField(
        queryset=AdoptionApplication.objects.filter(status__in=['completed', 'returned']))
    task = serializers.PrimaryKeyRelatedField(
        queryset=AdoptionUpdateTask.objects.all(), required=False, allow_null=True)
    images = serializers.ListField(
        child=serializers.URLField(max_length=500), required=False, default=list)

    class Meta:
        model = AdoptionUpdate
        fields = ['id', 'application', 'task', 'content', 'images',
                  'video_url', 'is_public', 'review_status', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        task = attrs.get('task')
        if task and task.application_id != attrs['application'].id:
            raise serializers.ValidationError({'task': '打卡任务与申请单不匹配'})
        return attrs

    def create(self, validated_data):
        manager = self.context['request'].user
        validated_data.setdefault('review_status', 'normal')
        with transaction.atomic():
            update = AdoptionUpdate.objects.create(
                source='staff', reviewed_by=manager,
                reviewed_at=timezone.now(), **validated_data)
            task = validated_data.get('task')
            if task and task.status in ('pending', 'overdue'):
                # 电话核实代替用户打卡 → 该期豁免
                AdoptionUpdateTask.objects.filter(pk=task.pk).update(
                    status='exempted', updated_at=timezone.now())
        if update.review_status == 'abnormal':
            dispatch_task('adoption.tasks.alert_abnormal_update', update.id)
        return update


# ============================================================
# 领养资格 / 违规
# ============================================================
class AdopterProfileSerializer(serializers.ModelSerializer):
    """C端: 我的领养资格"""
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AdopterProfile
        fields = ['status', 'status_display', 'restricted_until', 'credit_score',
                  'applied_count', 'cancelled_count', 'adopted_count',
                  'returned_count', 'violation_count']


class AdopterProfileAdminSerializer(AdopterProfileSerializer):
    user_phone = serializers.CharField(source='user.phone', read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta(AdopterProfileSerializer.Meta):
        fields = ['id', 'user', 'user_phone', 'user_name'] + \
                 AdopterProfileSerializer.Meta.fields + \
                 ['remark', 'created_at', 'updated_at']
        read_only_fields = ['user', 'applied_count', 'cancelled_count',
                            'adopted_count', 'returned_count', 'violation_count',
                            'created_at', 'updated_at']

    def get_user_name(self, obj):
        return getattr(obj.user, 'display_name', None) or str(obj.user_id)


class AdoptionViolationSerializer(serializers.ModelSerializer):
    violation_type_display = serializers.CharField(source='get_violation_type_display', read_only=True)
    penalty_display = serializers.CharField(source='get_penalty_display', read_only=True)

    class Meta:
        model = AdoptionViolation
        fields = ['id', 'user', 'application', 'violation_type', 'violation_type_display',
                  'penalty', 'penalty_display', 'restrict_days', 'credit_deduct',
                  'description', 'evidence_images', 'is_system', 'operator', 'created_at']


class AdoptionViolationCreateSerializer(serializers.ModelSerializer):
    """管理员记录违规并联动资格处罚(同事务内更新 AdopterProfile)"""
    evidence_images = serializers.ListField(
        child=serializers.URLField(max_length=500), required=False, default=list)

    class Meta:
        model = AdoptionViolation
        fields = ['id', 'user', 'application', 'violation_type', 'penalty',
                  'restrict_days', 'credit_deduct', 'description',
                  'evidence_images', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        if attrs.get('penalty') == 'restrict' and not attrs.get('restrict_days'):
            raise serializers.ValidationError({'restrict_days': '限制领养必须填写限制天数'})
        return attrs

    def create(self, validated_data):
        manager = self.context['request'].user
        deduct = validated_data.get('credit_deduct') or 0

        with transaction.atomic():
            violation = AdoptionViolation.objects.create(
                operator=manager, is_system=False, **validated_data)

            profile, _ = (AdopterProfile.objects.select_for_update()
                          .get_or_create(user=validated_data['user']))
            profile.violation_count += 1
            profile.credit_score = max(0, profile.credit_score - deduct)

            penalty = validated_data['penalty']
            if penalty == 'restrict':
                until = timezone.now() + timedelta(days=validated_data['restrict_days'])
                # 已有更晚的限制则保留更晚者
                if not (profile.restricted_until and profile.restricted_until > until):
                    profile.restricted_until = until
                profile.status = 'restricted'
            elif penalty == 'ban':
                profile.status = 'banned'
                profile.restricted_until = None
            profile.save()

        dispatch_task('adoption.tasks.notify_violation', violation.id)
        return violation


# ============================================================
# 收藏
# ============================================================
class PetFavoriteSerializer(serializers.ModelSerializer):
    pet = PetBriefSerializer(read_only=True)

    class Meta:
        model = PetFavorite
        fields = ['id', 'pet', 'created_at']