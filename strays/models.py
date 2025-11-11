from django.db import models
from django.utils import timezone

from user.models import User


class StrayAnimal(models.Model):
    """流浪动物记录模型 - 简化版"""

    # 动物类型选择
    ANIMAL_TYPE_CHOICES = [
        ('dog', '狗'),
        ('cat', '猫'),
        ('rabbit', '兔子'),
        ('bird', '鸟'),
        ('other', '其他'),
    ]

    # 性别选择
    GENDER_CHOICES = [
        ('male', '雄性'),
        ('female', '雌性'),
        ('unknown', '未知'),
    ]

    # 体型选择
    SIZE_CHOICES = [
        ('tiny', '迷你型'),  # 如仓鼠、小鸟
        ('small', '小型'),  # 如小型犬、猫
        ('medium', '中型'),  # 如中型犬
        ('large', '大型'),  # 如大型犬
    ]

    # 健康状态
    HEALTH_STATUS_CHOICES = [
        ('good', '良好'),
        ('normal', '一般'),
        ('injured', '受伤'),
        ('sick', '生病'),
        ('unknown', '未知'),
    ]

    # 状态选择
    STATUS_CHOICES = [
        ('active', '活跃'),  # 正常在外流浪
        ('missing', '失踪'),  # 一段时间未见
        ('rescued', '已救助'),  # 已被救助
        ('adopted', '已领养'),  # 已被领养
    ]

    # 基本信息
    reporter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reported_animals',
        verbose_name='记录者'
    )
    animal_type = models.CharField(
        max_length=20,
        choices=ANIMAL_TYPE_CHOICES,
        verbose_name='动物类型',
        db_index=True
    )
    nickname = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='昵称'
    )

    # 外观特征
    breed = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='品种'
    )
    primary_color = models.CharField(
        max_length=30,
        verbose_name='主要颜色'
    )
    secondary_color = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        verbose_name='次要颜色'
    )
    size = models.CharField(
        max_length=20,
        choices=SIZE_CHOICES,
        verbose_name='体型大小'
    )
    gender = models.CharField(
        max_length=20,
        choices=GENDER_CHOICES,
        default='unknown',
        verbose_name='性别'
    )
    estimated_age = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        verbose_name='估计年龄',
        help_text='例如：幼崽、1-2岁、老年等'
    )

    # 特殊特征（重要字段，用于识别）
    distinctive_features = models.TextField(
        blank=True,
        null=True,
        verbose_name='显著特征',
        help_text='例如：左耳有缺口、尾巴断了一截、额头有白斑等'
    )

    # 健康和行为
    health_status = models.CharField(
        max_length=20,
        choices=HEALTH_STATUS_CHOICES,
        default='unknown',
        verbose_name='健康状态'
    )
    is_friendly = models.BooleanField(
        default=True,
        verbose_name='是否亲人'
    )
    behavior_notes = models.TextField(
        blank=True,
        null=True,
        verbose_name='行为特点',
        help_text='例如：胆小、活泼、喜欢晒太阳等'
    )

    # 地址信息
    province = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        db_index=True,
        verbose_name='省份'
    )
    city = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        db_index=True,
        verbose_name='城市'
    )
    district = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        db_index=True,
        verbose_name='区县'
    )
    detail_address = models.CharField(
        max_length=200,
        verbose_name='详细地址'
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name='经度'
    )
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name='纬度'
    )
    location_tips = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name='位置提示',
        help_text='例如：常在垃圾桶附近、喜欢在树下休息等'
    )

    # 图片（使用OSS的URL）
    main_image_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='主图片URL'
    )
    image_urls = models.JSONField(
        default=list,
        blank=True,
        verbose_name='其他图片URLs',
        help_text='JSON格式的图片URL列表'
    )

    # 状态信息
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        verbose_name='当前状态',
        db_index=True
    )

    # 时间信息
    first_seen_date = models.DateField(
        verbose_name='首次发现日期',
        help_text='第一次看到这只动物的日期'
    )
    last_seen_date = models.DateField(
        verbose_name='最后见到日期',
        help_text='最近一次看到这只动物的日期'
    )

    # 互动统计
    view_count = models.PositiveIntegerField(
        default=0,
        verbose_name='浏览次数'
    )
    interaction_count = models.PositiveIntegerField(
        default=0,
        verbose_name='互动次数',
        help_text='包括评论、点赞等'
    )

    # 其他信息
    additional_notes = models.TextField(
        blank=True,
        null=True,
        verbose_name='补充说明'
    )

    # 记录控制
    is_active = models.BooleanField(
        default=True,
        verbose_name='是否有效',
        help_text='是否显示在列表中'
    )

    # 时间戳
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='创建时间'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='更新时间'
    )

    class Meta:
        db_table = 'stray_animals'
        verbose_name = '流浪动物'
        verbose_name_plural = '流浪动物'
        ordering = ['-last_seen_date', '-created_at']
        indexes = [
            models.Index(fields=['status', '-last_seen_date']),
            models.Index(fields=['province', 'city', 'district']),
            models.Index(fields=['animal_type', 'status']),
            models.Index(fields=['latitude', 'longitude']),
        ]

    def __str__(self):
        return f"{self.get_animal_type_display()} - {self.nickname or '未命名'} ({self.city or ''}{self.district or ''})"

    def increase_view_count(self):
        """增加浏览次数"""
        self.view_count += 1
        self.save(update_fields=['view_count'])

    def increase_interaction_count(self):
        """增加互动次数"""
        self.interaction_count += 1
        self.save(update_fields=['interaction_count'])


class StrayAnimalInteraction(models.Model):
    """流浪动物互动记录"""

    INTERACTION_TYPE_CHOICES = [
        ('comment', '评论'),
        ('like', '点赞'),
        ('feed', '投喂'),
        ('sighting', '目击'),
        ('care', '照料'),
    ]

    animal = models.ForeignKey(
        StrayAnimal,
        on_delete=models.CASCADE,
        related_name='interactions',
        verbose_name='流浪动物'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='animal_interactions',
        verbose_name='用户'
    )

    interaction_type = models.CharField(
        max_length=20,
        choices=INTERACTION_TYPE_CHOICES,
        verbose_name='互动类型'
    )

    content = models.TextField(
        blank=True,
        null=True,
        verbose_name='互动内容',
        help_text='评论内容或其他描述'
    )

    # 如果是目击或投喂，可以更新位置
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name='互动位置纬度'
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name='互动位置经度'
    )

    # 图片证明（OSS URL）
    image_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name='图片URL'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='互动时间'
    )

    class Meta:
        db_table = 'stray_animal_interactions'
        verbose_name = '动物互动'
        verbose_name_plural = '动物互动'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['animal', 'interaction_type']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.get_interaction_type_display()} - {self.animal.nickname or '未命名'}"

    def save(self, *args, **kwargs):
        """保存时更新动物的互动计数"""
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new:
            self.animal.increase_interaction_count()