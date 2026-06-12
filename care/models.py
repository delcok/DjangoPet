from decimal import Decimal
from django.db import models
from django.utils import timezone
from pet.models import Pet, PetCategory, PetBreed


# ---------------------------------------------------------------------------
# 公共枚举
# ---------------------------------------------------------------------------
class LifeStage(models.TextChoices):
    JUVENILE = "juvenile", "幼年"
    ADULT = "adult", "成年"
    SENIOR = "senior", "老年"



# ===========================================================================
# 一、食谱知识库(按 PetCategory 归一化,品种只决定体重)
# ===========================================================================
class Ingredient(models.Model):
    CATEGORY_CHOICES = [
        ("protein", "蛋白质"), ("vegetable", "蔬菜"), ("carb", "碳水"),
        ("fat", "油脂"), ("supplement", "补剂"), ("other", "其他"),
    ]
    name = models.CharField(max_length=64, unique=True, verbose_name="食材名")
    name_en = models.CharField(max_length=128, blank=True, default="", verbose_name="英文名")
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default="other", verbose_name="分类")
    kcal_per_100g = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="每100g热量kcal")
    common_allergen = models.BooleanField(default=False, verbose_name="是否常见过敏原")
    # 安全护栏:对哪些大类有毒(洋葱/葱蒜/巧克力/木糖醇/葡萄...)→ 生成食谱时绝不选入
    toxic_to_categories = models.ManyToManyField(PetCategory, blank=True, related_name="toxic_ingredients", verbose_name="对其有毒的大类")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "pet_ingredient"
        verbose_name = "食材"
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["category"])]

    def __str__(self):
        return self.name


class FunctionalTag(models.Model):
    """功能标签:低敏/美毛/肠胃/关节/控重 等,可对接健康状况与加权挑选"""
    code = models.SlugField(max_length=30, unique=True, verbose_name="代码")
    name = models.CharField(max_length=32, verbose_name="名称")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    class Meta:
        db_table = "pet_functional_tag"
        verbose_name = "功能标签"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.name


class FeedingRule(models.Model):
    """补 Excel 缺失的『每日餐数』+ 能量系数 + 年龄段阈值 + 喂食时间窗,数据驱动不写死"""
    category = models.ForeignKey(PetCategory, on_delete=models.CASCADE, related_name="feeding_rules", verbose_name="大类")
    life_stage = models.CharField(max_length=16, choices=LifeStage.choices, verbose_name="年龄段")
    meals_per_day = models.PositiveSmallIntegerField(default=2, verbose_name="每日餐数")  # 幼年3-4 成年2 老年2-3
    mer_factor_min = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.2"), verbose_name="能量系数下限")
    mer_factor_max = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("2.0"), verbose_name="能量系数上限")
    age_min_months = models.PositiveIntegerField(default=0, verbose_name="年龄下限(月)")
    age_max_months = models.PositiveIntegerField(null=True, blank=True, verbose_name="年龄上限(月,空=无上限)")
    # 喂食时间窗(相对固定,保证规律):[["07:30","08:30"], ["17:30","18:30"]];条数应≈meals_per_day
    feed_windows = models.JSONField(default=list, blank=True, verbose_name="喂食时间窗",
                                    help_text='[["07:30","08:30"],["17:30","18:30"]]')

    class Meta:
        db_table = "pet_feeding_rule"
        verbose_name = "投喂规则"
        verbose_name_plural = verbose_name
        constraints = [models.UniqueConstraint(fields=["category", "life_stage"], name="uniq_feeding_rule")]

    def __str__(self):
        return f"{self.category}-{self.get_life_stage_display()}: {self.meals_per_day}餐/天"


class Recipe(models.Model):
    """食谱:按 (category, life_stage, day_index) 归一化,全部品种共用。
       day_index 只是『7 个变体之一』的索引,生成器会按种子打散到具体日期,周与周不雷同。
       breed 可空——非空为品种专属食谱,优先级高于大类默认。"""
    STATUS_CHOICES = [("draft", "草稿"), ("published", "已发布")]
    DAY_CHOICES = [(1, "变体1"), (2, "变体2"), (3, "变体3"), (4, "变体4"), (5, "变体5"), (6, "变体6"), (7, "变体7")]

    category = models.ForeignKey(PetCategory, on_delete=models.PROTECT, related_name="recipes", verbose_name="大类")
    life_stage = models.CharField(max_length=16, choices=LifeStage.choices, verbose_name="年龄段")
    day_index = models.PositiveSmallIntegerField(choices=DAY_CHOICES, verbose_name="变体序号(1-7)")
    breed = models.ForeignKey(PetBreed, on_delete=models.SET_NULL, null=True, blank=True, related_name="recipes", verbose_name="品种专属(可空)")

    title = models.CharField(max_length=128, verbose_name="食谱名")
    primary_benefits = models.TextField(blank=True, default="", verbose_name="主要功效")
    preparation_steps = models.JSONField(default=list, blank=True, verbose_name="做法步骤(数组)")
    est_kcal_per_100g = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("120.0"), verbose_name="能量密度kcal/100g")
    # Excel 单餐区间,仅作安全上下限兜底
    ref_portion_min_g = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="单餐参考下限g")
    ref_portion_max_g = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="单餐参考上限g")
    functional_tags = models.ManyToManyField(FunctionalTag, blank=True, related_name="recipes", verbose_name="功能标签")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="published", verbose_name="状态")
    version = models.PositiveIntegerField(default=1, verbose_name="版本号")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "pet_recipe"
        verbose_name = "食谱"
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(fields=["category", "life_stage", "day_index", "breed"], name="uniq_recipe_scope"),
        ]
        indexes = [models.Index(fields=["category", "life_stage", "day_index", "status"])]

    def __str__(self):
        scope = self.breed.name if self.breed_id else self.category.name
        return f"{scope}-{self.get_life_stage_display()}-{self.get_day_index_display()}"


class RecipeIngredient(models.Model):
    """食谱-食材明细:归一化的『食材明细与克数』"""
    UNIT_CHOICES = [("g", "克"), ("ml", "毫升"), ("piece", "个"), ("pinch", "少许")]

    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="items", verbose_name="食谱")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="recipe_items", verbose_name="食材")
    amount = models.DecimalField(max_digits=7, decimal_places=2, verbose_name="数量")
    unit = models.CharField(max_length=8, choices=UNIT_CHOICES, default="g", verbose_name="单位")
    prep_note = models.CharField(max_length=64, blank=True, default="", verbose_name="处理方式")  # 切碎/焯水...
    order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")

    class Meta:
        db_table = "pet_recipe_ingredient"
        verbose_name = "食谱食材明细"
        verbose_name_plural = verbose_name
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["recipe", "ingredient"], name="uniq_item_per_recipe")]

    def __str__(self):
        return f"{self.ingredient}{self.amount}{self.unit}"


# ===========================================================================
# 二、养育档案扩展(OneToOne 挂到你现有的 Pet,不改主表;不含 is_neutered)
# ===========================================================================
class PetCareProfile(models.Model):
    """养育建议引擎的结构化输入。补 Pet 上没有、但生成建议需要的偏好类字段。
       绝育状态读 pet.is_neutered(已在你的 Pet 上)。"""
    ACTIVITY_CHOICES = [("low", "低"), ("moderate", "中"), ("high", "高")]
    FOOD_PREF_CHOICES = [("fresh", "鲜食"), ("dry", "干粮"), ("mixed", "混合")]

    pet = models.OneToOneField(Pet, on_delete=models.CASCADE, related_name="care_profile", verbose_name="宠物")
    activity_level = models.CharField(max_length=10, choices=ACTIVITY_CHOICES, default="moderate", verbose_name="活动量")
    food_preference = models.CharField(max_length=10, choices=FOOD_PREF_CHOICES, default="mixed", verbose_name="喂食偏好")
    allergies = models.ManyToManyField(Ingredient, blank=True, related_name="allergic_pets", verbose_name="过敏食材")
    disliked_ingredients = models.ManyToManyField(Ingredient, blank=True, related_name="disliked_by_pets", verbose_name="不爱吃的食材")
    # 个人偏好时间窗,生成日程时优先于规则默认:[["07:00","08:00"], ...]
    preferred_feeding_windows = models.JSONField(default=list, blank=True, verbose_name="偏好喂食时间窗")
    preferred_walk_windows = models.JSONField(default=list, blank=True, verbose_name="偏好遛弯时间窗")
    walks_per_day_override = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="每日遛弯次数(覆盖默认)")
    enable_reminders = models.BooleanField(default=True, verbose_name="是否开启提醒")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "pet_care_profile"
        verbose_name = "宠物养育档案"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.pet} 养育档案"


# ===========================================================================
# 三、护理内容池 + 规则(非喂食任务:遛弯/玩耍/训练/梳毛/丰容)
# ===========================================================================
class CareActivity(models.Model):
    """非喂食任务的"内容库",和 Recipe 对称。
       生成器从池中按『轮换 + 排重 + 加权』挑一条填进 CareTask,
       让遛弯/玩耍/训练天天不同,而后台维护的仍是有限的几十条数据。"""
    TASK_TYPE_CHOICES = [
        ("walk", "遛弯"), ("play", "玩耍互动"), ("train", "训练"),
        ("groom", "梳毛洗护"), ("enrich", "丰容/嗅闻"),
    ]
    category = models.ForeignKey(PetCategory, on_delete=models.PROTECT, related_name="activities", verbose_name="大类")
    life_stage = models.CharField(max_length=16, blank=True, default="", verbose_name="年龄段(空=通用)")  # 取值同 LifeStage
    task_type = models.CharField(max_length=12, choices=TASK_TYPE_CHOICES, db_index=True, verbose_name="任务类型")
    title = models.CharField(max_length=64, verbose_name="活动名")          # 嗅闻寻宝/拔河/捡球/基础坐下
    instructions = models.TextField(blank=True, default="", verbose_name="玩法/步骤")
    tip_text = models.CharField(max_length=255, blank=True, default="", verbose_name="一句话建议")
    duration_min = models.PositiveSmallIntegerField(default=15, verbose_name="建议时长(分钟)")
    difficulty = models.PositiveSmallIntegerField(default=1, verbose_name="难度(1-3)")
    media_url = models.URLField(blank=True, default="", verbose_name="演示图/视频")
    weight = models.PositiveSmallIntegerField(default=10, verbose_name="出现权重")  # 越大越常被选中
    # 只对特定养育方式生效(室内猫不需户外遛弯)→ 存 Pet.raising_mode 取值;空=全部
    applies_raising_modes = models.JSONField(default=list, blank=True, verbose_name="适用养育方式")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "pet_care_activity"
        verbose_name = "护理活动库"
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["category", "task_type", "life_stage", "is_active"])]

    def __str__(self):
        return f"{self.category}-{self.get_task_type_display()}:{self.title}"


class CareRule(models.Model):
    """非喂食类排期规则,数据驱动 → 决定『每天几次、在哪些时间窗』,再由内容池填充具体活动。
       例:成犬室外饲养 → 遛弯 2 次/天,时间窗 [07:00-08:30] 与 [18:00-19:30]。"""
    category = models.ForeignKey(PetCategory, on_delete=models.CASCADE, related_name="care_rules", verbose_name="大类")
    life_stage = models.CharField(max_length=16, choices=LifeStage.choices, blank=True, default="", verbose_name="年龄段(空=通用)")
    task_type = models.CharField(max_length=16, verbose_name="任务类型")  # 取值对应 CareActivity / CareTask
    frequency_per_day = models.PositiveSmallIntegerField(default=1, verbose_name="每日次数")
    default_duration_min = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="单次时长(分钟)")
    # 时间窗(给区间不给精确点):[["07:00","08:30"], ["18:00","19:30"]];条数应≈frequency_per_day
    time_windows = models.JSONField(default=list, blank=True, verbose_name="时间窗",
                                    help_text='[["07:00","08:30"],["18:00","19:30"]]')
    # 只对特定养育方式生效;空=全部
    applies_raising_modes = models.JSONField(default=list, blank=True, verbose_name="适用养育方式")
    tip_text = models.CharField(max_length=255, blank=True, default="", verbose_name="建议文案")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "pet_care_rule"
        verbose_name = "护理排期规则"
        verbose_name_plural = verbose_name
        # 同一 (大类, 年龄段, 任务类型) 只允许一条规则。
        # 否则 _care_rules() 会同时返回多条,生成器在同一个计划内把同类任务(如遛弯)排多遍 → 计划内重复。
        # 注意:迁移前需先清掉库里已存在的重复行,否则建约束会失败。
        constraints = [
            models.UniqueConstraint(fields=["category", "life_stage", "task_type"],
                                    name="uniq_care_rule_scope"),
        ]
        indexes = [models.Index(fields=["category", "task_type", "is_active"])]

    def __str__(self):
        return f"{self.category}-{self.task_type} x{self.frequency_per_day}/天"


# ===========================================================================
# 四、日程引擎:CarePlan → CareTask
# ===========================================================================
class CarePlan(models.Model):
    """养育计划实例:用户选完宠物后生成一段周期(如一周)的日程"""
    STATUS_CHOICES = [("active", "进行中"), ("archived", "已归档")]

    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name="care_plans", verbose_name="宠物")
    start_date = models.DateField(verbose_name="开始日期")
    end_date = models.DateField(verbose_name="结束日期")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="active", verbose_name="状态")
    # 生成时快照,保证历史稳定 + 体重变化可追溯
    weight_at_generation = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="生成时体重kg")
    life_stage_at_generation = models.CharField(max_length=16, choices=LifeStage.choices, blank=True, default="", verbose_name="生成时年龄段")
    daily_kcal_target = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="每日热量目标DER")
    meals_per_day = models.PositiveSmallIntegerField(default=2, verbose_name="每日餐数")
    # 可复现随机种子:seed = hash(pet_id, 周序号),看起来随机但稳定可复现,便于调试/重算
    generation_seed = models.BigIntegerField(default=0, verbose_name="生成随机种子")
    algorithm_version = models.CharField(max_length=16, default="v1", verbose_name="算法版本")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "pet_care_plan"
        verbose_name = "养育计划"
        verbose_name_plural = verbose_name
        indexes = [models.Index(fields=["pet", "status", "start_date"])]

    def __str__(self):
        return f"{self.pet} {self.start_date}~{self.end_date}"


class CareTask(models.Model):
    """统一的『一条待办』:喂食/遛弯/梳毛/玩耍/补水/训练/健康。
       这就是给宠物主看的——今天该做什么、在哪个时间段做。
       时间用区间(scheduled_start ~ scheduled_end),不给精确点。"""
    TASK_TYPE_CHOICES = [
        ("feed", "喂食"), ("walk", "遛弯"), ("groom", "梳毛洗护"), ("play", "玩耍互动"),
        ("water", "补水"), ("train", "训练"), ("health", "健康(驱虫/疫苗)"), ("other", "其他"),
    ]
    STATUS_CHOICES = [("pending", "待办"), ("done", "已完成"), ("skipped", "跳过")]

    care_plan = models.ForeignKey(CarePlan, on_delete=models.CASCADE, related_name="tasks", verbose_name="养育计划")
    pet = models.ForeignKey(Pet, on_delete=models.CASCADE, related_name="care_tasks", verbose_name="宠物")  # 冗余,加速"今日"查询
    task_type = models.CharField(max_length=12, choices=TASK_TYPE_CHOICES, db_index=True, verbose_name="任务类型")
    date = models.DateField(db_index=True, verbose_name="日期")
    # 时间区间:展示如 "07:30–08:30"
    scheduled_start = models.TimeField(null=True, blank=True, verbose_name="时间窗开始")
    scheduled_end = models.TimeField(null=True, blank=True, verbose_name="时间窗结束")
    title = models.CharField(max_length=64, verbose_name="标题")  # 早餐/遛狗/梳毛
    tip_text = models.CharField(max_length=255, blank=True, default="", verbose_name="建议文案")

    # 喂食任务专用:引用食谱 + 按体重算出的克数 + 快照
    recipe = models.ForeignKey(Recipe, on_delete=models.SET_NULL, null=True, blank=True, related_name="care_tasks", verbose_name="食谱(喂食时)")
    portion_g = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="本餐克数")
    kcal = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, verbose_name="本餐热量")
    ingredients_snapshot = models.JSONField(default=list, blank=True, verbose_name="食材明细快照")

    # 非喂食任务专用:引用具体活动(和 recipe 对称;也用于排重/展示/打卡)
    activity = models.ForeignKey(CareActivity, on_delete=models.SET_NULL, null=True, blank=True, related_name="care_tasks", verbose_name="护理活动(非喂食时)")
    payload = models.JSONField(default=dict, blank=True, verbose_name="附加数据")  # 如 {"duration_min": 30}

    # 提醒:可在 scheduled_start 前若干分钟推送,复用你 PetHealthRecord.remind_date 的扫描思路
    reminder_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="提醒时间")
    is_reminder_sent = models.BooleanField(default=False, verbose_name="是否已推送")

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending", verbose_name="状态")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    completion_note = models.CharField(max_length=255, blank=True, default="", verbose_name="完成备注")

    created_at = models.DateTimeField(default=timezone.now, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "pet_care_task"
        verbose_name = "养育待办"
        verbose_name_plural = verbose_name
        ordering = ["date", "scheduled_start"]
        indexes = [
            models.Index(fields=["pet", "date", "scheduled_start"]),    # "今日待办"高频
            models.Index(fields=["reminder_at", "is_reminder_sent"]),   # 提醒扫描
        ]

    def __str__(self):
        return f"{self.pet} {self.date} {self.get_task_type_display()}"