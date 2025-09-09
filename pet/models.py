from django.db import models

from bill.models import ServiceOrder
from price.models import Service
from user.models import User
from django.utils import timezone


class PetCategory(models.Model):
    name = models.CharField(max_length=50, verbose_name="分类名称")
    icon = models.URLField(verbose_name="分类图标")
    sort_order = models.IntegerField(default=0, verbose_name="排序")
    is_active = models.BooleanField(default=True)

class Pet(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="主人")
    category = models.ForeignKey(PetCategory, on_delete=models.CASCADE, verbose_name="宠物分类")
    name = models.CharField(max_length=50, verbose_name="宠物名称")
    breed = models.CharField(max_length=100, verbose_name="品种")
    age = models.IntegerField(verbose_name="年龄(月)")
    gender = models.CharField(max_length=1, choices=[('M', '雄性'), ('F', '雌性')])
    weight = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="体重(kg)")
    color = models.CharField(max_length=50, verbose_name="毛色")
    avatar =  models.URLField(blank=True, null=True)
    personality = models.TextField(verbose_name="性格特点")
    health_status = models.TextField(verbose_name="健康状况")
    vaccination_record = models.TextField(verbose_name="疫苗记录")
    special_notes = models.TextField(null=True, blank=True, verbose_name="特殊说明")
    created_at = models.DateTimeField(default=timezone.now)  # 自动创建时间
    updated_at = models.DateTimeField(auto_now=True)


class PetDiary(models.Model):
    """
    宠物日记：用户日常记录 + 服务商服务记录
    """
    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name='diaries', verbose_name="宠物")

    title = models.CharField(max_length=100, verbose_name="标题")
    content = models.TextField(verbose_name="内容")
    images = models.JSONField(default=list, blank=True, verbose_name="图片列表")
    videos = models.JSONField(default=list, blank=True, verbose_name="视频列表")

    # 时间记录
    diary_date = models.DateField(default=timezone.now, verbose_name="日记日期")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")


class PetServiceRecord(models.Model):
    """
    宠物服务记录：用户预约的宠物服务记录
    """
    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name='service_records', verbose_name="宠物")
    service_provider = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="服务提供者")
    related_order = models.OneToOneField(ServiceOrder, on_delete=models.CASCADE, verbose_name="关联订单")

    # 服务信息
    service_type = models.ForeignKey(Service, on_delete=models.CASCADE, verbose_name="服务类型")
    service_title = models.CharField(max_length=100, verbose_name="服务标题")
    service_content = models.TextField(verbose_name="服务内容描述")

    # 服务过程记录
    service_start_time = models.DateTimeField(verbose_name="服务开始时间")
    service_end_time = models.DateTimeField(verbose_name="服务结束时间")
    service_duration = models.IntegerField(verbose_name="服务时长(分钟)")

    # 宠物状况记录
    pet_condition_before = models.TextField(verbose_name="服务前宠物状况")
    pet_condition_after = models.TextField(verbose_name="服务后宠物状况")
    pet_behavior_notes = models.TextField(blank=True, null=True, verbose_name="宠物行为记录")

    # 服务结果
    service_result = models.TextField(verbose_name="服务结果")
    professional_recommendations = models.TextField(blank=True, null=True, verbose_name="专业建议")
    next_service_suggestion = models.TextField(blank=True, null=True, verbose_name="下次服务建议")

    # 多媒体记录
    before_images = models.JSONField(default=list, blank=True, verbose_name="服务前照片")
    after_images = models.JSONField(default=list, blank=True, verbose_name="服务后照片")
    process_videos = models.JSONField(default=list, blank=True, verbose_name="服务过程视频")

    # 额外信息
    special_notes = models.TextField(blank=True, null=True, verbose_name="特殊说明")
    customer_feedback = models.TextField(blank=True, null=True, verbose_name="客户反馈")

    # 时间记录
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")



