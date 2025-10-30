from django.db import models
from django.utils import timezone
from bill.models import ServiceOrder
from price.models import Service
from user.models import User


class PetCategory(models.Model):
    """宠物分类"""
    name = models.CharField(max_length=50, verbose_name="分类名称", unique=True)
    icon = models.URLField(verbose_name="分类图标", blank=True, null=True)
    sort_order = models.IntegerField(default=0, verbose_name="排序", db_index=True)
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'pet_category'
        verbose_name = "宠物分类"
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class Pet(models.Model):
    """宠物信息 - 用户隐私数据，仅主人可见"""
    GENDER_CHOICES = [
        ('M', '雄性'),
        ('F', '雌性'),
        ('U', '未知')
    ]

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='pets',
        verbose_name="主人"
    )
    category = models.ForeignKey(
        PetCategory,
        on_delete=models.PROTECT,
        related_name='pets',
        verbose_name="宠物分类"
    )
    name = models.CharField(max_length=50, verbose_name="宠物名称", blank=True, null=True)
    breed = models.CharField(max_length=100, verbose_name="品种", blank=True, null=True)
    birth_date = models.DateField(verbose_name="出生日期", blank=True, null=True)
    gender = models.CharField(
        max_length=1,
        choices=GENDER_CHOICES,
        default='U',
        verbose_name="性别"
    )
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name="体重(kg)",
        help_text="单位：千克",
        blank=True,
        null=True
    )
    color = models.CharField(max_length=50, verbose_name="毛色", blank=True, null=True)
    avatar = models.URLField(blank=True, null=True, verbose_name="头像")
    personality = models.TextField(blank=True, null=True, verbose_name="性格特点")
    health_status = models.TextField(blank=True, null=True, verbose_name="健康状况")
    vaccination_record = models.TextField(blank=True, null=True, verbose_name="疫苗记录")
    special_notes = models.TextField(blank=True, null=True, verbose_name="特殊说明")
    is_deleted = models.BooleanField(default=False, verbose_name="是否删除")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'pet'
        verbose_name = "宠物"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['category', 'is_deleted']),
        ]

    def __str__(self):
        return f"{self.name or '未命名'} ({self.owner.username})"

    @property
    def age_months(self):
        """计算年龄（月）"""
        if not self.birth_date:
            return None
        from datetime import date
        today = date.today()
        months = (today.year - self.birth_date.year) * 12 + today.month - self.birth_date.month
        if today.day < self.birth_date.day:
            months -= 1
        return max(0, months)

    @property
    def age_years(self):
        """计算年龄（年）"""
        if self.age_months is None:
            return None
        return self.age_months // 12


class PetDiary(models.Model):
    """
    宠物日记 - 用户隐私数据，仅主人可见
    包括用户日常记录 + 服务商服务记录
    """
    DIARY_TYPE_CHOICES = [
        ('daily', '日常记录'),
        ('service', '服务记录'),
    ]

    pet = models.ForeignKey(
        Pet,
        on_delete=models.CASCADE,
        related_name='diaries',
        verbose_name="宠物"
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='pet_diaries',
        verbose_name="记录人",
        help_text="可以是宠物主人或服务提供者",
        blank=True,
        null=True
    )
    diary_type = models.CharField(
        max_length=10,
        choices=DIARY_TYPE_CHOICES,
        default='daily',
        verbose_name="日记类型"
    )

    title = models.CharField(max_length=100, verbose_name="标题", blank=True, null=True)
    content = models.TextField(verbose_name="内容", blank=True, null=True)
    images = models.JSONField(default=list, blank=True, verbose_name="图片列表")
    videos = models.JSONField(default=list, blank=True, verbose_name="视频列表")

    # 时间记录
    diary_date = models.DateField(default=timezone.now, verbose_name="日记日期")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'pet_diary'
        verbose_name = "宠物日记"
        verbose_name_plural = verbose_name
        ordering = ['-diary_date', '-created_at']
        indexes = [
            models.Index(fields=['pet', '-diary_date']),
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['diary_type', '-created_at']),
        ]

    def __str__(self):
        pet_name = self.pet.name or '未命名宠物'
        title = self.title or '无标题'
        return f"{pet_name}的日记 - {title}"


class PetServiceRecord(models.Model):
    """
    宠物服务记录 - 用户隐私数据，仅主人可见
    服务完成后的详细记录（服务商填写）
    """
    # 关联订单（从订单获取基础信息）
    related_order = models.OneToOneField(
        ServiceOrder,
        on_delete=models.CASCADE,
        related_name='service_record',
        verbose_name="关联订单"
    )
    # 关联日记（服务完成后可创建服务日记）
    related_diary = models.OneToOneField(
        PetDiary,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='service_record',
        verbose_name="关联服务日记"
    )

    # 服务过程记录（实际执行时间）
    actual_start_time = models.DateTimeField(verbose_name="实际开始时间", blank=True, null=True)
    actual_end_time = models.DateTimeField(verbose_name="实际结束时间", blank=True, null=True)
    actual_duration = models.IntegerField(null=True, blank=True, verbose_name="实际时长(分钟)")

    # 宠物状况记录
    pet_condition_before = models.TextField(verbose_name="服务前宠物状况", blank=True, null=True)
    pet_condition_after = models.TextField(verbose_name="服务后宠物状况", blank=True, null=True)
    pet_behavior_notes = models.TextField(blank=True, null=True, verbose_name="宠物行为记录")

    # 服务结果
    service_summary = models.TextField(verbose_name="服务总结", blank=True, null=True)
    professional_recommendations = models.TextField(blank=True, null=True, verbose_name="专业建议")
    next_service_suggestion = models.TextField(blank=True, null=True, verbose_name="下次服务建议")

    # 多媒体记录
    before_images = models.JSONField(default=list, blank=True, verbose_name="服务前照片")
    after_images = models.JSONField(default=list, blank=True, verbose_name="服务后照片")
    process_videos = models.JSONField(default=list, blank=True, verbose_name="服务过程视频")

    # 额外信息
    special_notes = models.TextField(blank=True, null=True, verbose_name="特殊说明")

    # 客户反馈（客户填写）
    customer_feedback = models.TextField(blank=True, null=True, verbose_name="客户反馈")
    rating = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="评分",
        help_text="1-5分"
    )

    # 时间记录
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'pet_service_record'
        verbose_name = "宠物服务记录"
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['related_order']),
            models.Index(fields=['-actual_start_time']),
        ]

    def __str__(self):
        return f"服务记录 - 订单#{self.related_order.id}"

    @property
    def pet(self):
        """获取服务的宠物"""
        return self.related_order.pets.first()

    @property
    def service_provider(self):
        """获取服务提供者"""
        return self.related_order.staff if self.related_order.staff else None

    def save(self, *args, **kwargs):
        # 自动计算实际服务时长
        if self.actual_start_time and self.actual_end_time and not self.actual_duration:
            duration = self.actual_end_time - self.actual_start_time
            self.actual_duration = int(duration.total_seconds() / 60)
        super().save(*args, **kwargs)