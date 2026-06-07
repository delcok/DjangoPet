"""
流浪宠物领养模块 — Django Models 设计 v2
配合自定义用户体系: users.User(C端用户,手机号主键体系)

═══════════════════════════════════════════════════════════
核心业务规则(本次确认的需求,全部落到字段/约束上)
═══════════════════════════════════════════════════════════
【规则1】一只宠物可被多人申请,但同时最多 max_applying(默认3)张"进行中"申请
    - StrayPet.applying_count 维护进行中申请数(冗余计数,事务内同步)
    - 满额后 pet.status = 'full',前台显示"申请名额已满",新申请被拦截
    - 有申请被拒绝/取消/过期 → 计数 -1,名额自动释放回 'available'

【规则2】管理员择优通过
    - 同一只宠物的多张申请由管理员对比审核,可打 review_score 辅助排序
    - 通过其中 1 张(approved)→ 其余进行中申请自动批量 rejected
      (reject_reason='本次未能匹配成功,感谢您的爱心'),并触发订阅消息
    - approved 后超过时限未完成线下交接 → 自动流转 'expired',名额释放,记一次爽约

【规则3】恶意用户停止领养资格
    - AdopterProfile(1对1扩展表,不污染 User 表): 资格状态 + 信用分 + 统计
    - AdoptionViolation: 违规记录(虚假资料/爽约/弃养/失联/拒不打卡...)
    - 提交申请前置校验 profile.can_apply();注意这与 User.is_banned(账号级封禁)
      是两个维度: 账号正常但领养资格可以被单独冻结

【规则4】领养完成后定期发动态(打卡)
    - completed 时按 update_plan(默认交接后第7/30/90/180天)批量生成 AdoptionUpdateTask
    - 用户在打卡窗口内提交 AdoptionUpdate(图文/视频,可同步为社区动态)
    - 定时任务扫描逾期 → 推送提醒 → 连续逾期 → 自动生成违规记录 → 冻结资格 + 人工介入

【提交申请的并发安全(无 service 层,实现位置: Serializer.create 内事务)】
    with transaction.atomic():
        pet = StrayPet.objects.select_for_update().get(id=pet_id)   # 行锁防超卖
        assert pet.status == 'available'
        assert pet.applying_count < pet.max_applying
        assert profile.can_apply
        # 条件唯一约束兜底"同人同宠仅一张进行中申请"
        app = AdoptionApplication.objects.create(...)
        pet.applying_count += 1
        if pet.applying_count >= pet.max_applying:
            pet.status = 'full'
        pet.save()
        ApplicationStatusLog.objects.create(...)

【Celery 分工(写逻辑收敛在 Serializer/View,异步与定时全走 Celery)】
    - 即时通知: 事务 on_commit 后按任务名投递(新申请提醒管理员/审核结果/打卡提醒/落选通知)
    - celery beat 定时任务:
        scan_approve_expired   每小时: approved 且超 approve_expire_at → expired,释放名额,记爽约
        scan_overdue_updates   每天:   pending 且过 due_end → overdue 推提醒;连续2期逾期 → 自动违规+冻结资格
        scan_restriction_lift  每天:   restricted 且过 restricted_until → 恢复 normal
"""
from django.db import models
from django.db.models import Q
from django.utils import timezone
import uuid

# C端用户(你的 user app: user.models.User)
APP_USER_MODEL = 'user.User'
# 平台管理员(managers.models.Manager): 审核申请、登记宠物、处理违规的操作主体
# ⚠️ 注意: 不要指向 staffs.Staff —— 那是商家端员工,与平台管理员是两套体系
MANAGER_MODEL = 'managers.Manager'


def default_update_plan():
    """领养后打卡计划: 交接完成后第 N 天需提交动态(可按宠物情况在申请单上单独调整)"""
    return [7, 30, 90, 180]


def gen_application_no() -> str:
    """业务单号: AD+日期+随机段,对外展示/客服沟通用,不暴露自增ID"""
    return 'AD{}{}'.format(timezone.now().strftime('%Y%m%d'), uuid.uuid4().hex[:8].upper())


# ============================================================
# 1. 流浪宠物档案
# ============================================================
class StrayPet(models.Model):

    SPECIES_CHOICES = [
        ('cat',   '猫'),
        ('dog',   '狗'),
        ('other', '其他'),
    ]

    GENDER_CHOICES = [
        ('male',    '公'),
        ('female',  '母'),
        ('unknown', '未知'),
    ]

    SIZE_CHOICES = [
        ('small',  '小型'),
        ('medium', '中型'),
        ('large',  '大型'),
    ]

    STATUS_CHOICES = [
        ('draft',     '待上架'),
        ('available', '可申请'),          # applying_count < max_applying
        ('full',      '申请名额已满'),     # 进行中申请达到上限,审核中
        ('handover',  '待交接'),          # 已有申请通过,等待线下交接
        ('adopted',   '已被领养'),
        ('paused',    '暂停领养'),         # 治疗/隔离观察等
        ('deceased',  '已离世'),
    ]

    # ---------- 基本信息 ----------
    name = models.CharField(max_length=50, verbose_name='昵称')
    species = models.CharField(max_length=10, choices=SPECIES_CHOICES, db_index=True, verbose_name='物种')
    breed = models.CharField(max_length=50, blank=True, default='田园/未知', verbose_name='品种')
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='unknown', verbose_name='性别')
    birth_date_est = models.DateField(null=True, blank=True, verbose_name='预估出生日期')
    age_text = models.CharField(max_length=30, blank=True, default='', verbose_name='年龄描述',
                                help_text='如"约2岁",流浪宠物年龄多为兽医估算')
    size = models.CharField(max_length=10, choices=SIZE_CHOICES, blank=True, default='', verbose_name='体型')
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name='体重(kg)')
    color = models.CharField(max_length=100, blank=True, default='', verbose_name='毛色/外观特征')

    # ---------- 健康信息 ----------
    is_sterilized = models.BooleanField(default=False, verbose_name='是否绝育')
    is_vaccinated = models.BooleanField(default=False, verbose_name='是否接种疫苗')
    vaccine_detail = models.CharField(max_length=200, blank=True, default='', verbose_name='疫苗详情')
    is_dewormed = models.BooleanField(default=False, verbose_name='是否驱虫')
    health_desc = models.TextField(blank=True, default='', verbose_name='健康状况描述')
    special_needs = models.TextField(blank=True, default='', verbose_name='特殊情况/残疾/慢性病',
                                     help_text='如猫藓恢复期、三脚、需长期处方粮,必须如实告知')

    # ---------- 性格习性 ----------
    personality = models.TextField(blank=True, default='', verbose_name='性格描述')
    good_with_kids = models.BooleanField(null=True, blank=True, verbose_name='亲近小孩(null=未知)')
    good_with_pets = models.BooleanField(null=True, blank=True, verbose_name='能与其他宠物相处(null=未知)')

    # ---------- 救助背景 ----------
    rescue_date = models.DateField(null=True, blank=True, verbose_name='救助日期')
    rescue_location = models.CharField(max_length=200, blank=True, default='', verbose_name='救助地点')
    rescue_story = models.TextField(blank=True, default='', verbose_name='救助故事')

    # ---------- 所在位置 ----------
    province = models.CharField(max_length=20, blank=True, default='', verbose_name='省')
    city = models.CharField(max_length=20, blank=True, default='', db_index=True, verbose_name='市')
    district = models.CharField(max_length=20, blank=True, default='', verbose_name='区/县')
    shelter_address = models.CharField(max_length=200, blank=True, default='', verbose_name='安置详细地址',
                                       help_text='仅后台可见,前台脱敏')

    # ---------- 领养条件与名额 ----------
    adoption_requirements = models.TextField(blank=True, default='', verbose_name='领养要求',
                                             help_text='如需封窗、同城优先、接受家访等')
    max_applying = models.PositiveSmallIntegerField(default=3, verbose_name='同时受理申请上限')
    applying_count = models.PositiveSmallIntegerField(default=0, verbose_name='进行中申请数',
                                                      help_text='冗余计数,事务内随申请增删同步')

    # ---------- 状态与运营 ----------
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='draft',
                              db_index=True, verbose_name='状态')
    cover_image = models.URLField(max_length=500, blank=True, default='', verbose_name='封面图')
    view_count = models.PositiveIntegerField(default=0, verbose_name='浏览量')
    favorite_count = models.PositiveIntegerField(default=0, verbose_name='收藏数')
    sort_weight = models.IntegerField(default=0, verbose_name='排序权重',
                                      help_text='运营置顶用;久未被申请的可调高曝光')

    adopted_at = models.DateTimeField(null=True, blank=True, verbose_name='领养完成时间',
                                      help_text='申请单 completed 时自动写入,统计/排序用')

    # ---------- 审计 ----------
    created_by = models.ForeignKey(MANAGER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name='registered_pets', verbose_name='登记人')
    is_deleted = models.BooleanField(default=False, verbose_name='软删除')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'stray_pets'
        verbose_name = '流浪宠物'
        verbose_name_plural = '流浪宠物'
        ordering = ['-sort_weight', '-created_at']
        indexes = [
            models.Index(fields=['status', 'species', 'city']),  # 列表页核心筛选组合
        ]

    def __str__(self):
        return f'{self.name}({self.get_species_display()})'

    @property
    def can_accept_application(self):
        """是否还能接收新申请"""
        return self.status == 'available' and self.applying_count < self.max_applying


# ============================================================
# 2. 宠物图片/视频
# ============================================================
class PetMedia(models.Model):

    MEDIA_TYPE_CHOICES = [
        ('image', '图片'),
        ('video', '视频'),
    ]

    pet = models.ForeignKey(StrayPet, on_delete=models.CASCADE, related_name='media', verbose_name='宠物')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES, default='image', verbose_name='类型')
    url = models.URLField(max_length=500, verbose_name='资源地址', help_text='OSS/COS 外链')
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='排序')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')

    class Meta:
        db_table = 'stray_pet_media'
        verbose_name = '宠物图片/视频'
        verbose_name_plural = '宠物图片/视频'
        ordering = ['sort_order', 'id']


# ============================================================
# 3. 领养资格档案(1对1扩展,照搬你们 UserWallet 的拆表思路)
# ============================================================
class AdopterProfile(models.Model):
    """
    领养资格档案 —— 恶意用户管控的核心。
    与 User.is_banned(账号级封禁)是两个维度:
    账号可以正常逛小程序,但领养资格可被单独冻结。
    首次提交申请时 get_or_create。
    """

    STATUS_CHOICES = [
        ('normal',     '正常'),
        ('restricted', '限制领养'),   # 有期限,restricted_until 到期自动恢复
        ('banned',     '永久禁止领养'),
    ]

    user = models.OneToOneField(APP_USER_MODEL, on_delete=models.CASCADE,
                                related_name='adopter_profile', verbose_name='用户')
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='normal',
                              db_index=True, verbose_name='资格状态')
    restricted_until = models.DateTimeField(null=True, blank=True, verbose_name='限制截止时间',
                                            help_text='status=restricted 时生效,到期由定时任务/惰性校验恢复')
    credit_score = models.PositiveSmallIntegerField(default=100, verbose_name='领养信用分',
                                                    help_text='满分100,违规扣分,可作为择优参考之一')

    # ---------- 行为统计(择优 + 风控信号) ----------
    applied_count = models.PositiveIntegerField(default=0, verbose_name='累计申请次数')
    cancelled_count = models.PositiveIntegerField(default=0, verbose_name='主动取消次数',
                                                  help_text='频繁申请又取消是恶意信号')
    adopted_count = models.PositiveIntegerField(default=0, verbose_name='成功领养次数')
    returned_count = models.PositiveIntegerField(default=0, verbose_name='退养次数')
    violation_count = models.PositiveIntegerField(default=0, verbose_name='违规次数')

    remark = models.CharField(max_length=200, blank=True, default='', verbose_name='后台备注')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'adopter_profiles'
        verbose_name = '领养资格档案'
        verbose_name_plural = '领养资格档案'

    def __str__(self):
        return f'{self.user_id} - {self.get_status_display()}(信用{self.credit_score})'

    @property
    def can_apply(self):
        """提交申请前的资格校验入口"""
        if self.status == 'banned':
            return False
        if self.status == 'restricted':
            if self.restricted_until and timezone.now() >= self.restricted_until:
                return True  # 到期,service 层顺手把状态恢复为 normal
            return False
        return True


# ============================================================
# 4. 领养申请单(核心业务表)
# ============================================================
class AdoptionApplication(models.Model):

    STATUS_CHOICES = [
        ('submitted', '已提交'),
        ('reviewing', '资料审核中'),
        ('interview', '待面谈/家访'),
        ('approved',  '审核通过,待交接'),
        ('completed', '领养完成'),
        ('rejected',  '已拒绝'),        # 含择优落选
        ('cancelled', '用户已取消'),
        ('expired',   '通过后逾期未交接'),  # 名额释放,计一次爽约
        ('returned',  '已退养'),         # completed 后退回,宠物重新上架
    ]

    # "进行中"状态集合: 占用宠物名额 + 参与条件唯一约束
    ACTIVE_STATUSES = ('submitted', 'reviewing', 'interview', 'approved')

    HOUSING_CHOICES = [
        ('own',    '自有住房'),
        ('rent',   '租房'),
        ('shared', '合租/宿舍'),
    ]

    application_no = models.CharField(max_length=32, unique=True, default=gen_application_no,
                                      verbose_name='申请单号')
    pet = models.ForeignKey(StrayPet, on_delete=models.PROTECT, related_name='applications',
                            verbose_name='申请宠物')
    applicant = models.ForeignKey(APP_USER_MODEL, on_delete=models.CASCADE,
                                  related_name='adoption_applications', verbose_name='申请用户')

    # ---------- 申请人资料快照(固化提交时刻,不随 User 表变更) ----------
    real_name = models.CharField(max_length=30, verbose_name='真实姓名')
    phone = models.CharField(max_length=20, verbose_name='联系电话',
                             help_text='默认取 User.phone,允许填写其他联系方式;前台展示脱敏')
    wechat_id = models.CharField(max_length=50, blank=True, default='', verbose_name='微信号')
    age = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='年龄')
    occupation = models.CharField(max_length=50, blank=True, default='', verbose_name='职业')
    address = models.CharField(max_length=200, verbose_name='常住地址')

    # ---------- 居住与家庭情况 ----------
    housing_type = models.CharField(max_length=10, choices=HOUSING_CHOICES, verbose_name='住房情况')
    landlord_allowed = models.BooleanField(null=True, blank=True, verbose_name='房东是否允许养宠(租房必填)')
    family_agreed = models.BooleanField(default=False, verbose_name='家人是否一致同意')
    has_children = models.BooleanField(default=False, verbose_name='家中是否有小孩')
    family_allergic = models.BooleanField(default=False, verbose_name='家人是否对毛发过敏')

    # ---------- 养宠经验与经济能力 ----------
    has_experience = models.BooleanField(default=False, verbose_name='是否有养宠经验')
    current_pets = models.CharField(max_length=200, blank=True, default='', verbose_name='现有宠物情况')
    monthly_budget = models.PositiveIntegerField(null=True, blank=True, verbose_name='预计每月养宠预算(元)')

    # ---------- 领养承诺 ----------
    accept_sterilization = models.BooleanField(default=False, verbose_name='承诺适龄绝育')
    accept_followup = models.BooleanField(default=False, verbose_name='接受定期回访与打卡')
    accept_window_sealing = models.BooleanField(null=True, blank=True, verbose_name='承诺封窗(领养猫)')

    reason = models.TextField(verbose_name='领养原因/想法')
    extra_answers = models.JSONField(default=dict, blank=True, verbose_name='扩展问卷答案',
                                     help_text='开放题(如搬家/生育后如何安置),加题不改表')

    # ---------- 审核流程(管理员处理 + 择优) ----------
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='submitted',
                              db_index=True, verbose_name='状态')
    review_score = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='审核评分',
                                                    help_text='0-100,管理员对比同宠物多张申请择优用')
    reviewer = models.ForeignKey(MANAGER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='reviewed_applications', verbose_name='审核人')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='最近审核时间')
    review_note = models.TextField(blank=True, default='', verbose_name='审核备注(仅内部)')
    reject_reason = models.CharField(max_length=200, blank=True, default='', verbose_name='拒绝原因(展示给用户)')

    # ---------- 交接环节 ----------
    approve_expire_at = models.DateTimeField(null=True, blank=True, verbose_name='交接截止时间',
                                             help_text='approved 时写入(如+7天),定时任务扫描逾期→expired')
    handover_at = models.DateTimeField(null=True, blank=True, verbose_name='交接完成时间')
    agreement_url = models.URLField(max_length=500, blank=True, default='', verbose_name='领养协议文件',
                                    help_text='电子协议PDF或纸质协议签字照片')

    # ---------- 领养后打卡计划 ----------
    update_plan = models.JSONField(default=default_update_plan, blank=True, verbose_name='打卡计划(天)',
                                   help_text='completed 时按此计划生成打卡任务,可按宠物情况单独调整')

    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'adoption_applications'
        verbose_name = '领养申请'
        verbose_name_plural = '领养申请'
        ordering = ['-created_at']
        constraints = [
            # 同一用户对同一只宠物,仅允许一条"进行中"申请(被拒后可再次申请)
            models.UniqueConstraint(
                fields=['pet', 'applicant'],
                condition=Q(status__in=['submitted', 'reviewing', 'interview', 'approved']),
                name='uniq_active_application',
            ),
        ]
        indexes = [
            models.Index(fields=['pet', 'status']),            # 后台: 同宠物申请对比(择优)
            models.Index(fields=['applicant', '-created_at']),  # 小程序: 我的申请列表
            models.Index(fields=['status', '-created_at']),     # 后台: 待办队列
        ]

    def __str__(self):
        return f'{self.application_no} - {self.real_name} 申请 {self.pet_id}'


# ============================================================
# 5. 申请状态流转日志(审计/客诉追溯)
# ============================================================
class ApplicationStatusLog(models.Model):
    application = models.ForeignKey(AdoptionApplication, on_delete=models.CASCADE,
                                    related_name='status_logs', verbose_name='关联申请')
    from_status = models.CharField(max_length=15, blank=True, default='', verbose_name='原状态')
    to_status = models.CharField(max_length=15, verbose_name='新状态')
    operator = models.ForeignKey(MANAGER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 verbose_name='操作人', help_text='系统自动流转时为空')
    remark = models.CharField(max_length=200, blank=True, default='', verbose_name='备注')
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='操作时间')

    class Meta:
        db_table = 'adoption_application_logs'
        verbose_name = '申请状态日志'
        verbose_name_plural = '申请状态日志'
        ordering = ['-created_at']


# ============================================================
# 6. 违规记录(恶意行为留痕,联动资格处罚)
# ============================================================
class AdoptionViolation(models.Model):

    TYPE_CHOICES = [
        ('fake_info',      '提供虚假资料'),
        ('no_show',        '面谈/交接爽约'),
        ('overdue_update', '长期未按时打卡'),
        ('lost_contact',   '领养后失联'),
        ('abandon',        '弃养'),
        ('abuse',          '虐待'),
        ('other',          '其他'),
    ]

    PENALTY_CHOICES = [
        ('warning',  '警告(扣信用分)'),
        ('restrict', '限制领养(带期限)'),
        ('ban',      '永久禁止领养'),
    ]

    user = models.ForeignKey(APP_USER_MODEL, on_delete=models.CASCADE,
                             related_name='adoption_violations', verbose_name='用户')
    application = models.ForeignKey(AdoptionApplication, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='violations', verbose_name='关联申请单')
    violation_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name='违规类型')
    penalty = models.CharField(max_length=10, choices=PENALTY_CHOICES, verbose_name='处罚措施')
    restrict_days = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='限制天数',
                                                     help_text='penalty=restrict 时填写')
    credit_deduct = models.PositiveSmallIntegerField(default=0, verbose_name='扣除信用分')
    description = models.TextField(blank=True, default='', verbose_name='违规描述')
    evidence_images = models.JSONField(default=list, blank=True, verbose_name='证据图片')
    is_system = models.BooleanField(default=False, verbose_name='是否系统自动判定',
                                    help_text='如连续逾期打卡由定时任务自动生成')
    operator = models.ForeignKey(MANAGER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='handled_violations', verbose_name='处理人')
    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='创建时间')

    class Meta:
        db_table = 'adoption_violations'
        verbose_name = '领养违规记录'
        verbose_name_plural = '领养违规记录'
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]


# ============================================================
# 7. 领养后打卡任务(系统按计划生成)
# ============================================================
class AdoptionUpdateTask(models.Model):

    STATUS_CHOICES = [
        ('pending',   '待打卡'),
        ('submitted', '已提交'),
        ('overdue',   '已逾期'),
        ('exempted',  '已豁免'),   # 特殊情况后台人工豁免
    ]

    application = models.ForeignKey(AdoptionApplication, on_delete=models.CASCADE,
                                    related_name='update_tasks', verbose_name='关联申请')
    period_no = models.PositiveSmallIntegerField(verbose_name='期数', help_text='第几期打卡,从1开始')
    due_start = models.DateTimeField(verbose_name='窗口开始时间')
    due_end = models.DateTimeField(verbose_name='窗口截止时间', help_text='如计划日前后各3天为打卡窗口')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending',
                              db_index=True, verbose_name='状态')
    reminded_at = models.DateTimeField(null=True, blank=True, verbose_name='最近提醒时间',
                                       help_text='微信订阅消息提醒,防重复推送')
    remind_count = models.PositiveSmallIntegerField(default=0, verbose_name='已提醒次数',
                                                    help_text='订阅消息一次授权只能推一条,控制提醒配额')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'adoption_update_tasks'
        verbose_name = '领养打卡任务'
        verbose_name_plural = '领养打卡任务'
        unique_together = ['application', 'period_no']
        indexes = [
            models.Index(fields=['status', 'due_end']),  # 定时任务扫描: 待打卡且已过截止 → overdue
        ]

    def __str__(self):
        return f'{self.application_id} 第{self.period_no}期 {self.get_status_display()}'


# ============================================================
# 8. 领养后动态(用户打卡内容 / 员工回访记录,同表两源)
# ============================================================
class AdoptionUpdate(models.Model):

    SOURCE_CHOICES = [
        ('user',  '领养人打卡'),
        ('staff', '员工回访代录'),   # 电话/上门回访的记录也存这张表,口径统一
    ]

    REVIEW_CHOICES = [
        ('pending',  '待查看'),
        ('normal',   '状态良好'),
        ('abnormal', '存在异常'),    # 异常 → 人工介入,必要时生成违规记录
    ]

    application = models.ForeignKey(AdoptionApplication, on_delete=models.CASCADE,
                                    related_name='updates', verbose_name='关联申请')
    task = models.ForeignKey(AdoptionUpdateTask, on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='updates', verbose_name='关联打卡任务',
                             help_text='为空表示计划外自主加更,不占任务')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='user', verbose_name='来源')
    content = models.TextField(blank=True, default='', verbose_name='文字内容')
    images = models.JSONField(default=list, blank=True, verbose_name='图片列表')
    video_url = models.URLField(max_length=500, blank=True, default='', verbose_name='视频地址')
    related_post_id = models.BigIntegerField(null=True, blank=True, verbose_name='关联社区动态ID',
                                             help_text='打卡同步发布到社区时记录,松耦合不做硬外键')
    is_public = models.BooleanField(default=True, verbose_name='是否公开展示',
                                    help_text='公开则展示在宠物详情页"领养后的TA",尊重领养人隐私选择')

    # 管理员对动态的查看结论
    review_status = models.CharField(max_length=10, choices=REVIEW_CHOICES, default='pending',
                                     db_index=True, verbose_name='查看结论')
    reviewed_by = models.ForeignKey(MANAGER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='reviewed_updates', verbose_name='查看人')
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name='查看时间')

    created_at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='提交时间')

    class Meta:
        db_table = 'adoption_updates'
        verbose_name = '领养后动态'
        verbose_name_plural = '领养后动态'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['application', '-created_at']),
        ]


# ============================================================
# 9. 宠物收藏(心愿单 + 订阅消息推送依据)
# ============================================================
class PetFavorite(models.Model):
    user = models.ForeignKey(APP_USER_MODEL, on_delete=models.CASCADE,
                             related_name='pet_favorites', verbose_name='用户')
    pet = models.ForeignKey(StrayPet, on_delete=models.CASCADE,
                            related_name='favorites', verbose_name='宠物')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='收藏时间')

    class Meta:
        db_table = 'stray_pet_favorites'
        verbose_name = '宠物收藏'
        verbose_name_plural = '宠物收藏'
        unique_together = ['user', 'pet']