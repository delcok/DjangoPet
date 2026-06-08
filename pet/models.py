from decimal import Decimal, InvalidOperation
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from bill.models import ServiceOrder
from user.models import User


class PetCategory(models.Model):
    """
    宠物大类（一级分类）：狗 / 猫 / 兔 / 爬宠 / 鸟类 / 其他 ……
    作为全生态平台的顶层物种分类，下面挂具体品种 PetBreed。
    """
    name = models.CharField(max_length=50, verbose_name="大类名称", unique=True)
    code = models.SlugField(
        max_length=30, unique=True, verbose_name="大类标识",
        help_text="稳定英文标识，前端按它匹配身份入口：dog/cat/rabbit/reptile/bird/other"
    )
    icon = models.URLField(verbose_name="分类图标", blank=True, null=True)
    description = models.CharField(max_length=200, blank=True, default="", verbose_name="简介")
    sort_order = models.IntegerField(default=0, verbose_name="排序", db_index=True)
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'pet_category'
        verbose_name = "宠物大类"
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class PetBreed(models.Model):
    """
    宠物品种（二级分类）：雪纳瑞 / 泰迪 属于「狗」；布偶 / 英短 属于「猫」。
    属公开参考数据。
    """
    SIZE_CHOICES = [
        ('mini', '迷你'),
        ('small', '小型'),
        ('medium', '中型'),
        ('large', '大型'),
        ('giant', '巨型'),
    ]

    category = models.ForeignKey(
        PetCategory,
        on_delete=models.CASCADE,
        related_name='breeds',
        verbose_name="所属大类"
    )
    name = models.CharField(max_length=80, verbose_name="品种名称")
    alias = models.CharField(
        max_length=200, blank=True, default="", verbose_name="别名/搜索词",
        help_text="逗号分隔，用于搜索，如：贵宾,VIP,泰迪"
    )
    size = models.CharField(
        max_length=10, choices=SIZE_CHOICES, blank=True, null=True, verbose_name="体型"
    )
    icon = models.URLField(blank=True, null=True, verbose_name="品种图标")
    is_common = models.BooleanField(default=False, db_index=True, verbose_name="是否热门")
    sort_order = models.IntegerField(default=0, db_index=True, verbose_name="排序")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'pet_breed'
        verbose_name = "宠物品种"
        verbose_name_plural = verbose_name
        ordering = ['-is_common', 'sort_order', 'id']
        constraints = [
            models.UniqueConstraint(fields=['category', 'name'], name='uniq_breed_per_category')
        ]
        indexes = [
            models.Index(fields=['category', 'is_active']),
        ]

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class Pet(models.Model):
    """宠物信息 - 用户隐私数据，仅主人可见"""
    GENDER_CHOICES = [
        ('M', '雄性'),
        ('F', '雌性'),
        ('U', '未知')
    ]
    ADOPTION_PERIOD_CHOICES = [
        ('under_3m', '不到3个月'),
        ('over_3m', '3个月以上'),
        ('unknown', '记不清了'),
    ]
    BCS_CHOICES = [
        (1, '严重偏瘦'),
        (2, '偏瘦'),
        (3, '理想体型'),
        (4, '偏胖'),
        (5, '肥胖'),
    ]
    RAISING_MODE_CHOICES = [
        ('indoor', '室内饲养'),
        ('outdoor', '室外饲养'),
        ('mixed', '半室内半室外'),
        ('free', '散养'),
    ]
    SPECIAL_PHASE_CHOICES = [
        ('normal', '正常'),
        ('pregnant', '怀孕中'),
        ('lactating', '哺乳期'),
        ('postop', '术后恢复'),
        ('senior', '老年期'),
        ('juvenile', '幼年期'),
    ]

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='pets',
        verbose_name="主人"
    )
    # 大类（必填）：快速建档只需选大类
    category = models.ForeignKey(
        PetCategory,
        on_delete=models.PROTECT,
        related_name='pets',
        verbose_name="大类"
    )
    # 品种（选填，后续完善）：优先从品种库选；选不到时用 breed_name 自填
    breed = models.ForeignKey(
        PetBreed,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pets',
        verbose_name="品种"
    )
    breed_name = models.CharField(
        max_length=80, blank=True, null=True, verbose_name="品种名称(快照/自定义)",
        help_text="选了品种库会自动回填其名称；串串/未知/库里没有时可手填"
    )

    name = models.CharField(max_length=50, verbose_name="宠物名称", blank=True, null=True)
    birth_date = models.DateField(verbose_name="出生日期", blank=True, null=True)
    adoption_period = models.CharField(
        max_length=10, choices=ADOPTION_PERIOD_CHOICES,
        blank=True, null=True, verbose_name="到家时长"
    )
    gender = models.CharField(
        max_length=1,
        choices=GENDER_CHOICES,
        default='U',
        verbose_name="性别"
    )
    is_neutered = models.BooleanField(default=False, verbose_name="是否绝育")
    weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name="体重(kg)",
        help_text="单位：千克（当前值缓存，最新一条体重记录回写）",
        blank=True,
        null=True
    )
    color = models.CharField(max_length=50, verbose_name="毛色", blank=True, null=True)
    avatar = models.URLField(blank=True, null=True, verbose_name="头像")
    personality = models.TextField(blank=True, null=True, verbose_name="性格特点")
    health_status = models.TextField(blank=True, null=True, verbose_name="健康状况")
    vaccination_record = models.TextField(blank=True, null=True, verbose_name="疫苗记录")
    special_notes = models.TextField(blank=True, null=True, verbose_name="特殊说明")

    # ===== 当前状态字段（profile 上展示的"一个值"，非流水）=====
    raising_mode = models.CharField(
        max_length=10, choices=RAISING_MODE_CHOICES,
        blank=True, null=True, verbose_name="养育方式"
    )
    special_phase = models.CharField(
        max_length=10, choices=SPECIAL_PHASE_CHOICES,
        blank=True, null=True, default='normal', verbose_name="特殊时期"
    )
    special_phase_date = models.DateField(
        blank=True, null=True, verbose_name="特殊时期开始日期"
    )

    # ===== 流水表的"当前值缓存"（由 PetHealthRecord 写时回写，profile 卡片直接读）=====
    weight_date = models.DateField(null=True, blank=True, verbose_name="体重记录日期")
    body_condition_score = models.IntegerField(
        choices=BCS_CHOICES, null=True, blank=True, verbose_name="体况评分"
    )
    bcs_date = models.DateField(null=True, blank=True, verbose_name="体况评估日期")

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
            models.Index(fields=['breed']),
        ]

    def __str__(self):
        return f"{self.name or '未命名'} ({self.owner.username})"

    def clean(self):
        # 品种必须属于所选大类（用于 admin / form 校验；API 侧由序列化器再校验一次）
        if self.breed_id and self.category_id and self.breed.category_id != self.category_id:
            raise ValidationError({'breed': '所选品种不属于该大类'})

    def save(self, *args, **kwargs):
        # 选了品种库 -> 回填名称快照（即便将来该品种被下架/删除，名称也不丢）
        if self.breed_id:
            self.breed_name = self.breed.name
        super().save(*args, **kwargs)

    @property
    def breed_display(self):
        """统一的品种展示：优先品种库名称，回退到自定义文本"""
        if self.breed_id:
            return self.breed.name
        return self.breed_name or ''

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


class PetHealthRecord(models.Model):
    """
    宠物健康记录（流水表）—— 会反复发生、要看历史 / 做提醒的健康事件。
    与 PetDiary 彻底分开：日记是用户主动写的图文记录；健康记录是结构化健康事件。
    类型细节放 data(JSON)；所有"下次提醒"统一收敛到 remind_date，驱动一个提醒列表。

    缓存策略：weight / bcs 的最新一条会回写到 Pet（当前值缓存），
    由 PetHealthRecordViewSet 的 perform_create/update/destroy 显式调用 sync_pet_health_cache 维护，
    不走信号机制。
    """
    RECORD_TYPE_CHOICES = [
        ('weight', '体重'),
        ('bcs', '体况评分'),
        ('deworming', '驱虫'),
        ('vaccine', '疫苗'),
        ('medical', '病史'),
    ]
    DEWORMING_KIND_CHOICES = [
        ('internal', '体内驱虫'),
        ('external', '体外驱虫'),
        ('both', '体内外联合'),
    ]

    pet = models.ForeignKey(
        Pet, on_delete=models.CASCADE, related_name='health_records', verbose_name="宠物"
    )
    record_type = models.CharField(
        max_length=20, choices=RECORD_TYPE_CHOICES, db_index=True, verbose_name="记录类型"
    )
    record_date = models.DateField(db_index=True, verbose_name="发生日期")
    remind_date = models.DateField(
        null=True, blank=True, db_index=True, verbose_name="下次提醒日期",
        help_text="驱虫/疫苗的下次时间、病史的复诊日期，统一用它驱动提醒"
    )
    # 各类型结构化细节：
    #   weight    -> {"weight": 5.5}
    #   bcs       -> {"score": 3}
    #   deworming -> {"kind": "internal", "drug": "大宠爱"}
    #   vaccine   -> {"name": "狂犬疫苗"}
    #   medical   -> {"diagnosis": "...", "hospital": "..."}
    data = models.JSONField(default=dict, blank=True, verbose_name="结构化数据")
    note = models.TextField(blank=True, default="", verbose_name="备注")
    images = models.JSONField(default=list, blank=True, verbose_name="图片列表")

    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'pet_health_record'
        verbose_name = "宠物健康记录"
        verbose_name_plural = verbose_name
        ordering = ['-record_date', '-created_at']
        indexes = [
            models.Index(fields=['pet', 'record_type', '-record_date']),  # 单类型时间线高频
            models.Index(fields=['pet', '-record_date']),                 # 全类型时间线
            models.Index(fields=['remind_date']),                         # 提醒列表
        ]

    def __str__(self):
        return f"{self.pet.name or '未命名'} - {self.get_record_type_display()} @ {self.record_date}"


def sync_pet_health_cache(pet, record_type):
    """
    把某类型的最新一条回写到 Pet 缓存字段（weight / bcs），供 profile 卡片直接读。
    在 ViewSet 的 perform_create/update/destroy 里显式调用（不用信号）。
    其它类型（驱虫/疫苗/病史）无缓存字段，直接跳过。
    删光某类型所有记录时：故意不清空 Pet 上的旧值（可能是建档手填的初始体重）。
    """
    if record_type not in ('weight', 'bcs'):
        return
    latest = (pet.health_records
              .filter(record_type=record_type)
              .order_by('-record_date', '-created_at')
              .first())
    if not latest:
        return

    update_fields = []
    if record_type == 'weight':
        w = (latest.data or {}).get('weight')
        if w not in (None, ''):
            try:
                pet.weight = Decimal(str(w))
                pet.weight_date = latest.record_date
                update_fields += ['weight', 'weight_date']
            except (InvalidOperation, ValueError, TypeError):
                pass
    elif record_type == 'bcs':
        score = (latest.data or {}).get('score')
        if score not in (None, ''):
            try:
                pet.body_condition_score = int(score)
                pet.bcs_date = latest.record_date
                update_fields += ['body_condition_score', 'bcs_date']
            except (ValueError, TypeError):
                pass

    if update_fields:
        update_fields.append('updated_at')
        pet.save(update_fields=update_fields)


class PetDiary(models.Model):
    """
    宠物日记 - 用户隐私数据，仅主人可见。
    统一时间线：日常 / 记账 / 病历 / 服务记录（成长打卡可选），用 diary_type 区分。
    类型相关的结构化字段按需填（amount 用于记账，next_visit_date 用于病历），
    其余非通用字段塞进 extra(JSON)，避免后续频繁加列。
    """
    DIARY_TYPE_CHOICES = [
        ('daily', '日常'),
        ('bill', '记账'),
        ('medical', '病历'),
        ('service', '服务记录'),
        ('growth', '成长'),   # 前端 tab 暂无，按需启用
    ]

    EXPENSE_TYPE_CHOICES = [
        ('food', '食品零食'),
        ('medical', '医疗'),
        ('grooming', '洗护美容'),
        ('supplies', '日用品'),
        ('toy', '玩具'),
        ('boarding', '寄养'),
        ('other', '其他'),
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
        db_index=True,
        verbose_name="日记类型"
    )

    title = models.CharField(max_length=100, verbose_name="标题", blank=True, null=True)
    content = models.TextField(verbose_name="内容", blank=True, null=True)
    images = models.JSONField(default=list, blank=True, verbose_name="图片列表")
    videos = models.JSONField(default=list, blank=True, verbose_name="视频列表")
    cover_image = models.URLField(max_length=500, blank=True, default="", verbose_name="封面图片")

    # ---- 记账(bill)专用，选填 ----
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="金额(元)"
    )
    expense_type = models.CharField(
        max_length=20, choices=EXPENSE_TYPE_CHOICES, null=True, blank=True, verbose_name="消费类型"
    )

    # ---- 病历(medical)专用，选填 ----
    hospital = models.CharField(max_length=100, blank=True, null=True, verbose_name="就诊机构")
    next_visit_date = models.DateField(null=True, blank=True, verbose_name="复诊日期")

    # ---- 类型相关的其它结构化数据（如成长记录的身高/体重），避免频繁加列 ----
    extra = models.JSONField(default=dict, blank=True, verbose_name="附加数据")

    # 时间记录
    diary_date = models.DateField(default=timezone.now, db_index=True, verbose_name="日记日期")
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
            models.Index(fields=['pet', 'diary_type', '-diary_date']),  # tab 筛选高频路径
        ]

    def __str__(self):
        pet_name = self.pet.name or '未命名宠物'
        title = self.title or '无标题'
        return f"{pet_name}的日记 - {title}"

    def save(self, *args, **kwargs):
        # 没设封面时，自动用第一张图片（兼容 images 为字符串数组或 {url,...} 对象数组）
        if not self.cover_image and isinstance(self.images, list) and self.images:
            first = self.images[0]
            self.cover_image = first.get('url', '') if isinstance(first, dict) else (first or '')
        super().save(*args, **kwargs)


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