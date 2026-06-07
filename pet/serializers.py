# -*- coding: utf-8 -*-
# @Time    : 2025/10/20 18:51
# @Author  : Delock

from rest_framework import serializers
from .models import PetCategory, PetBreed, Pet, PetHealthRecord, PetDiary, PetServiceRecord


class PetBreedSerializer(serializers.ModelSerializer):
    """宠物品种序列化器（公开参考数据）"""
    size_display = serializers.CharField(source='get_size_display', read_only=True, allow_null=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = PetBreed
        fields = [
            'id', 'category', 'category_name', 'name', 'alias',
            'size', 'size_display', 'icon', 'is_common', 'sort_order'
        ]


class PetCategorySerializer(serializers.ModelSerializer):
    """宠物大类序列化器"""
    # breed_count 由视图集 annotate 注入，避免逐个分类查询品种数（N+1）
    breed_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = PetCategory
        fields = [
            'id', 'name', 'code', 'icon', 'description', 'sort_order',
            'is_active', 'breed_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class PetHealthRecordSerializer(serializers.ModelSerializer):
    """
    宠物健康记录序列化器（CRUD 通用）
    按 record_type 校验 data 结构；校验宠物归属。
    """
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    record_type_display = serializers.CharField(source='get_record_type_display', read_only=True)
    summary = serializers.SerializerMethodField()  # 给时间线列表一行展示用

    class Meta:
        model = PetHealthRecord
        fields = [
            'id', 'pet', 'pet_name', 'record_type', 'record_type_display',
            'record_date', 'remind_date', 'data', 'note', 'images',
            'summary', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_summary(self, obj):
        d = obj.data or {}
        t = obj.record_type
        if t == 'weight':
            w = d.get('weight')
            return f"{w}kg" if w not in (None, '') else ''
        if t == 'bcs':
            return dict(Pet.BCS_CHOICES).get(d.get('score'), '')
        if t == 'deworming':
            kind = dict(PetHealthRecord.DEWORMING_KIND_CHOICES).get(d.get('kind'), '')
            return ' '.join(x for x in [kind, d.get('drug') or ''] if x)
        if t == 'vaccine':
            return d.get('name') or ''
        if t == 'medical':
            return d.get('diagnosis') or ''
        return ''

    def validate_pet(self, value):
        """只能给自己的宠物记录"""
        user = self.context['request'].user
        if value.owner_id != getattr(user, 'id', None):
            raise serializers.ValidationError("您没有权限为该宠物添加健康记录")
        return value

    def validate(self, attrs):
        # 合并 instance 已有值，兼容 partial update
        rt = attrs.get('record_type') or getattr(self.instance, 'record_type', None)
        data = attrs.get('data') if 'data' in attrs else (getattr(self.instance, 'data', {}) or {})
        rec_date = attrs.get('record_date') or getattr(self.instance, 'record_date', None)
        rem_date = attrs.get('remind_date') if 'remind_date' in attrs \
            else getattr(self.instance, 'remind_date', None)

        data = data or {}
        errors = {}

        if rt == 'weight':
            try:
                if float(data.get('weight')) <= 0:
                    errors['data'] = "体重(data.weight)必须大于 0"
            except (TypeError, ValueError):
                errors['data'] = "体重(data.weight)必须是数字"
        elif rt == 'bcs':
            try:
                if int(data.get('score')) not in (1, 2, 3, 4, 5):
                    errors['data'] = "体况评分(data.score)必须是 1-5"
            except (TypeError, ValueError):
                errors['data'] = "体况评分(data.score)必须是 1-5 的整数"
        elif rt == 'deworming':
            if data.get('kind') and data['kind'] not in dict(PetHealthRecord.DEWORMING_KIND_CHOICES):
                errors['data'] = "驱虫类型(data.kind)非法"
        elif rt == 'vaccine':
            if not data.get('name'):
                errors['data'] = "疫苗名称(data.name)必填"
        elif rt == 'medical':
            if not data.get('diagnosis'):
                errors['data'] = "症状/诊断(data.diagnosis)必填"

        if rem_date and rec_date and rem_date < rec_date:
            errors['remind_date'] = "提醒日期不能早于发生日期"

        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class PetListSerializer(serializers.ModelSerializer):
    """宠物列表序列化器（简化版）"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_code = serializers.CharField(source='category.code', read_only=True)
    breed_display = serializers.CharField(read_only=True)
    age_display = serializers.SerializerMethodField()
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)

    class Meta:
        model = Pet
        fields = [
            'id', 'name', 'category', 'category_name', 'category_code',
            'breed', 'breed_display',
            'avatar', 'gender', 'gender_display', 'age_display',
            'weight', 'special_phase',
            'created_at'
        ]

    def get_age_display(self, obj):
        """返回年龄显示"""
        if obj.age_months is None:
            return None
        years = obj.age_years
        months = obj.age_months % 12
        if years > 0:
            return f"{years}岁{months}个月" if months > 0 else f"{years}岁"
        return f"{months}个月"


class PetDetailSerializer(serializers.ModelSerializer):
    """宠物详情序列化器"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_code = serializers.CharField(source='category.code', read_only=True)
    breed_detail = PetBreedSerializer(source='breed', read_only=True)
    breed_display = serializers.CharField(read_only=True)
    owner_name = serializers.CharField(source='owner.username', read_only=True)
    age_years = serializers.IntegerField(read_only=True)
    age_months = serializers.IntegerField(read_only=True)
    gender_display = serializers.CharField(source='get_gender_display', read_only=True)
    adoption_period_display = serializers.CharField(
        source='get_adoption_period_display', read_only=True, allow_null=True
    )
    bcs_display = serializers.CharField(
        source='get_body_condition_score_display', read_only=True, allow_null=True
    )
    raising_mode_display = serializers.CharField(
        source='get_raising_mode_display', read_only=True, allow_null=True
    )
    special_phase_display = serializers.CharField(
        source='get_special_phase_display', read_only=True, allow_null=True
    )
    current_health = serializers.SerializerMethodField()

    class Meta:
        model = Pet
        fields = [
            'id', 'owner', 'owner_name', 'category', 'category_name', 'category_code',
            'breed', 'breed_detail', 'breed_name', 'breed_display',
            'name', 'birth_date', 'adoption_period', 'adoption_period_display',
            'gender', 'gender_display', 'weight', 'weight_date', 'color', 'avatar',
            'body_condition_score', 'bcs_display', 'bcs_date',
            'raising_mode', 'raising_mode_display',
            'special_phase', 'special_phase_display', 'special_phase_date',
            'personality', 'health_status', 'vaccination_record', 'special_notes',
            'current_health', 'age_years', 'age_months', 'created_at', 'updated_at'
        ]
        read_only_fields = ['owner', 'created_at', 'updated_at', 'age_years', 'age_months']

    def create(self, validated_data):
        # 自动设置当前用户为宠物主人
        validated_data['owner'] = self.context['request'].user
        return super().create(validated_data)

    def validate_weight(self, value):
        """验证体重"""
        if value is not None and value <= 0:
            raise serializers.ValidationError("体重必须大于0")
        return value

    def validate(self, data):
        """品种必须属于所选大类（兼容创建/部分更新两种场景）"""
        category = data.get('category') or getattr(self.instance, 'category', None)
        # partial update 时 breed 可能没传，用实例已有值
        breed = data['breed'] if 'breed' in data else getattr(self.instance, 'breed', None)
        if breed and category and breed.category_id != category.id:
            raise serializers.ValidationError({'breed': '所选品种不属于该大类'})
        return data

    def get_current_health(self, obj):
        """
        各健康类型的最新一条汇总（单一数据源 = 流水表，永远新鲜）。
        依赖视图 prefetch_related('health_records')，否则会 N+1。
        """
        latest = {}
        for r in obj.health_records.all():   # 已按 -record_date 排序，首见即最新
            latest.setdefault(r.record_type, r)
        dw, vc, md = latest.get('deworming'), latest.get('vaccine'), latest.get('medical')
        return {
            'weight': obj.weight, 'weight_date': obj.weight_date,
            'bcs': obj.body_condition_score, 'bcs_date': obj.bcs_date,
            'last_deworming_date': dw.record_date if dw else None,
            'deworming_kind': (dw.data or {}).get('kind') if dw else None,
            'next_deworming_date': dw.remind_date if dw else None,
            'last_vaccine_date': vc.record_date if vc else None,
            'last_vaccine_name': (vc.data or {}).get('name') if vc else None,
            'next_vaccine_date': vc.remind_date if vc else None,
            'last_medical_date': md.record_date if md else None,
            'last_medical_diagnosis': (md.data or {}).get('diagnosis') if md else None,
            'next_visit_date': md.remind_date if md else None,
        }


class PetDiaryListSerializer(serializers.ModelSerializer):
    """宠物日记列表序列化器"""
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True, allow_null=True)
    diary_type_display = serializers.CharField(source='get_diary_type_display', read_only=True)
    expense_type_display = serializers.CharField(
        source='get_expense_type_display', read_only=True, allow_null=True
    )
    image_count = serializers.SerializerMethodField()
    video_count = serializers.SerializerMethodField()

    class Meta:
        model = PetDiary
        fields = [
            'id', 'pet', 'pet_name', 'author', 'author_name',
            'diary_type', 'diary_type_display', 'title', 'cover_image',
            'amount', 'expense_type', 'expense_type_display',
            'diary_date', 'image_count', 'video_count', 'created_at'
        ]

    def get_image_count(self, obj):
        return len(obj.images) if obj.images else 0

    def get_video_count(self, obj):
        return len(obj.videos) if obj.videos else 0


class PetDiaryDetailSerializer(serializers.ModelSerializer):
    """宠物日记详情序列化器"""
    pet_name = serializers.CharField(source='pet.name', read_only=True)
    author_name = serializers.CharField(source='author.username', read_only=True, allow_null=True)
    diary_type_display = serializers.CharField(source='get_diary_type_display', read_only=True)
    expense_type_display = serializers.CharField(
        source='get_expense_type_display', read_only=True, allow_null=True
    )

    class Meta:
        model = PetDiary
        fields = [
            'id', 'pet', 'pet_name', 'author', 'author_name',
            'diary_type', 'diary_type_display', 'title', 'content',
            'images', 'videos', 'cover_image',
            'amount', 'expense_type', 'expense_type_display',
            'hospital', 'next_visit_date', 'extra',
            'diary_date', 'created_at', 'updated_at'
        ]
        read_only_fields = ['author', 'created_at', 'updated_at']

    def create(self, validated_data):
        # 自动设置当前用户为记录人
        validated_data['author'] = self.context['request'].user
        return super().create(validated_data)

    def validate_pet(self, value):
        """验证宠物是否属于当前用户（只能给自己的宠物创建日记）"""
        user = self.context['request'].user
        if value.owner_id != getattr(user, 'id', None):
            raise serializers.ValidationError("您没有权限为该宠物创建日记")
        return value

    def validate(self, data):
        """验证数据完整性"""
        # 如果设置了封面图，确保它在图片列表中（兼容字符串/对象数组）
        images = data.get('images')
        cover_image = data.get('cover_image')
        if cover_image and isinstance(images, list) and images:
            urls = [(img.get('url') if isinstance(img, dict) else img) for img in images]
            if cover_image not in urls:
                raise serializers.ValidationError("封面图片必须在图片列表中")

        # 记账类型建议带金额（仅提示性校验，按需可放开/收紧）
        if data.get('diary_type') == 'bill' and data.get('amount') is None and not self.instance:
            raise serializers.ValidationError({'amount': '记账请填写金额'})

        return data


class PetServiceRecordListSerializer(serializers.ModelSerializer):
    """宠物服务记录列表序列化器"""
    pet_name = serializers.SerializerMethodField()
    service_name = serializers.SerializerMethodField()
    provider_name = serializers.SerializerMethodField()
    order_number = serializers.SerializerMethodField()
    order_status = serializers.CharField(source='related_order.status', read_only=True)

    class Meta:
        model = PetServiceRecord
        fields = [
            'id', 'related_order', 'order_number', 'order_status',
            'pet_name', 'service_name', 'provider_name',
            'actual_start_time', 'actual_end_time', 'actual_duration',
            'rating', 'created_at'
        ]

    def get_pet_name(self, obj):
        """获取宠物名称"""
        pet = obj.pet
        return pet.name if pet else None

    def get_service_name(self, obj):
        """获取服务名称 - 修复：使用 base_service 而不是 service"""
        try:
            if obj.related_order and obj.related_order.base_service:
                return obj.related_order.base_service.name
        except Exception:
            pass
        return None

    def get_provider_name(self, obj):
        """获取服务提供者名称"""
        provider = obj.service_provider
        return provider.username if provider else None

    def get_order_number(self, obj):
        """获取订单ID作为订单号"""
        return f"#{obj.related_order.id}" if obj.related_order else None


class PetServiceRecordDetailSerializer(serializers.ModelSerializer):
    """宠物服务记录详情序列化器"""
    pet_info = serializers.SerializerMethodField()
    service_info = serializers.SerializerMethodField()
    provider_info = serializers.SerializerMethodField()
    order_info = serializers.SerializerMethodField()
    diary_info = serializers.SerializerMethodField()

    class Meta:
        model = PetServiceRecord
        fields = [
            'id', 'related_order', 'related_diary', 'order_info',
            'pet_info', 'service_info', 'provider_info', 'diary_info',
            'actual_start_time', 'actual_end_time', 'actual_duration',
            'pet_condition_before', 'pet_condition_after', 'pet_behavior_notes',
            'service_summary', 'professional_recommendations', 'next_service_suggestion',
            'before_images', 'after_images', 'process_videos',
            'special_notes', 'customer_feedback', 'rating',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at', 'actual_duration']

    def get_pet_info(self, obj):
        """获取宠物信息"""
        pet = obj.pet
        if pet:
            return {
                'id': pet.id,
                'name': pet.name,
                'breed': pet.breed_display,
                'avatar': pet.avatar,
                'gender': pet.gender,
                'gender_display': pet.get_gender_display()
            }
        return None

    def get_service_info(self, obj):
        """获取服务信息 - 修复：使用 base_service 而不是 service"""
        try:
            if obj.related_order and obj.related_order.base_service:
                service = obj.related_order.base_service
                return {
                    'id': service.id,
                    'name': service.name,
                }
        except Exception:
            pass
        return None

    def get_provider_info(self, obj):
        """获取服务提供者信息"""
        provider = obj.service_provider
        if provider:
            return {
                'id': provider.id,
                'username': provider.username,
            }
        return None

    def get_order_info(self, obj):
        """获取订单信息"""
        order = obj.related_order
        return {
            'id': order.id,
            'order_number': f"#{order.id}",
            'status': order.status,
            'status_display': order.get_status_display(),
        }

    def get_diary_info(self, obj):
        """获取关联日记信息"""
        if obj.related_diary:
            diary = obj.related_diary
            return {
                'id': diary.id,
                'title': diary.title,
                'diary_date': diary.diary_date,
            }
        return None

    def validate(self, data):
        """验证时间逻辑"""
        start_time = data.get('actual_start_time')
        end_time = data.get('actual_end_time')

        if start_time and end_time:
            if end_time <= start_time:
                raise serializers.ValidationError("结束时间必须晚于开始时间")

        # 验证评分范围
        rating = data.get('rating')
        if rating is not None and (rating < 1 or rating > 5):
            raise serializers.ValidationError("评分必须在1-5之间")

        return data


class PetServiceRecordCreateSerializer(serializers.ModelSerializer):
    """宠物服务记录创建序列化器（服务商使用）"""

    class Meta:
        model = PetServiceRecord
        fields = [
            'related_order', 'actual_start_time', 'actual_end_time',
            'pet_condition_before', 'pet_condition_after', 'pet_behavior_notes',
            'service_summary', 'professional_recommendations', 'next_service_suggestion',
            'before_images', 'after_images', 'process_videos', 'special_notes'
        ]

    def validate_related_order(self, value):
        """验证订单状态和权限"""
        user = self.context['request'].user

        # 检查是否已存在服务记录
        if hasattr(value, 'service_record'):
            raise serializers.ValidationError("该订单已有服务记录")

        # 检查是否是服务提供者
        if value.staff != user:
            raise serializers.ValidationError("您没有权限为该订单创建服务记录")

        # 检查订单状态
        if value.status != 'completed':
            raise serializers.ValidationError("只能为已完成的订单创建服务记录")

        return value

    def validate(self, data):
        """验证时间逻辑"""
        start_time = data.get('actual_start_time')
        end_time = data.get('actual_end_time')

        if start_time and end_time:
            if end_time <= start_time:
                raise serializers.ValidationError("结束时间必须晚于开始时间")

        return data


class PetServiceRecordUpdateSerializer(serializers.ModelSerializer):
    """宠物服务记录更新序列化器（用于客户反馈）"""

    class Meta:
        model = PetServiceRecord
        fields = ['customer_feedback', 'rating']

    def validate_rating(self, value):
        """验证评分"""
        if value is not None and (value < 1 or value > 5):
            raise serializers.ValidationError("评分必须在1-5之间")
        return value