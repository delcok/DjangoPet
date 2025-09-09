from django.db import models
from django.utils import timezone
from user.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator


class BaseModel(models.Model):
    """基础模型类，提供通用字段"""
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        abstract = True


class PostCategory(BaseModel):
    """帖子分类"""
    name = models.CharField(max_length=50, unique=True, verbose_name="分类名称")
    slug = models.SlugField(max_length=50, unique=True, verbose_name="URL标识")
    icon = models.CharField(max_length=100, blank=True, default="", verbose_name="分类图标")
    color = models.CharField(
        max_length=7,
        default="#FF6B6B",
        validators=[RegexValidator(r'^#[0-9A-Fa-f]{6}$', '请输入有效的颜色代码')],
        verbose_name="主题色"
    )
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否启用")

    # 统计字段
    post_count = models.PositiveIntegerField(default=0, verbose_name="帖子数量")

    class Meta:
        db_table = 'post_categories'
        verbose_name = '帖子分类'
        verbose_name_plural = '帖子分类'
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name


class Post(BaseModel):
    """社区帖子"""

    POST_TYPE_CHOICES = [
        ('image', '图文'),
        ('text', '纯文字'),
        ('video', '视频'),
    ]

    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('pending', '待审核'),
        ('reviewing', '审核中'),
        ('approved', '审核通过'),
        ('rejected', '审核拒绝'),
        ('hidden', '已隐藏'),
        ('banned', '已封禁'),
        ('deleted', '已删除'),
    ]

    # 基础信息
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='posts',
        db_index=True,
        verbose_name="作者"
    )
    category = models.ForeignKey(
        PostCategory,
        on_delete=models.PROTECT,  # 改为PROTECT，防止误删分类
        null=True,
        blank=True,
        db_index=True,
        verbose_name="分类"
    )
    post_type = models.CharField(
        max_length=10,
        choices=POST_TYPE_CHOICES,
        default='image',
        db_index=True,
        verbose_name="帖子类型"
    )

    # 内容
    title = models.CharField(max_length=100, db_index=True, verbose_name="标题")
    content = models.TextField(verbose_name="内容")

    # 多媒体内容 - 使用独立的Media模型更灵活
    cover_image = models.URLField(max_length=500, blank=True, default="", verbose_name="封面图片")

    # 位置信息
    location = models.CharField(max_length=100, blank=True, default="", db_index=True, verbose_name="位置")
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="纬度"
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True, verbose_name="经度"
    )

    # 互动统计 - 使用PositiveIntegerField
    view_count = models.PositiveIntegerField(default=0, verbose_name="浏览量")
    like_count = models.PositiveIntegerField(default=0, db_index=True, verbose_name="点赞数")
    comment_count = models.PositiveIntegerField(default=0, verbose_name="评论数")
    collect_count = models.PositiveIntegerField(default=0, verbose_name="收藏数")
    share_count = models.PositiveIntegerField(default=0, verbose_name="分享数")

    # 推荐权重
    hot_score = models.FloatField(default=0, db_index=True, verbose_name="热度分数")
    quality_score = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(100)],
        verbose_name="内容质量分"
    )

    # 管理字段
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name="审核状态"
    )
    is_featured = models.BooleanField(default=False, db_index=True, verbose_name="是否精选")
    is_top = models.BooleanField(default=False, db_index=True, verbose_name="是否置顶")

    # 审核相关
    reviewer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_posts',
        verbose_name="审核人"
    )
    review_note = models.TextField(blank=True, default="", verbose_name="审核备注")
    reject_reason = models.CharField(max_length=200, blank=True, default="", verbose_name="拒绝原因")
    reviewed_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="审核时间")

    # 自动审核
    auto_review_score = models.FloatField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        verbose_name="自动审核分数"
    )
    review_priority = models.PositiveSmallIntegerField(default=0, db_index=True, verbose_name="审核优先级")

    # 违规处理
    violation_type = models.CharField(max_length=50, blank=True, default="", verbose_name="违规类型")
    violation_count = models.PositiveSmallIntegerField(default=0, verbose_name="违规次数")
    report_count = models.PositiveSmallIntegerField(default=0, verbose_name="举报次数")

    # 时间字段
    published_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="发布时间")
    last_active_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="最后活跃时间")

    class Meta:
        db_table = 'posts'
        verbose_name = '帖子'
        verbose_name_plural = '帖子'
        ordering = ['-is_top', '-hot_score', '-published_at']
        indexes = [
            models.Index(fields=['author', 'status', '-published_at']),
            models.Index(fields=['category', 'status', '-hot_score']),
            models.Index(fields=['status', 'review_priority', '-created_at']),
            models.Index(fields=['-last_active_at']),
        ]

    def __str__(self):
        return f"{self.author.username} - {self.title}"

    def save(self, *args, **kwargs):
        # 发布时间逻辑
        if not self.published_at and self.status == 'approved':
            self.published_at = timezone.now()
            self.last_active_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def is_published(self):
        """是否已发布"""
        return self.status == 'approved'

    @property
    def engagement_rate(self):
        """互动率"""
        if self.view_count == 0:
            return 0
        interactions = self.like_count + self.comment_count + self.collect_count
        return round((interactions / self.view_count) * 100, 2)


class PostMedia(BaseModel):
    """帖子媒体文件"""

    MEDIA_TYPE_CHOICES = [
        ('image', '图片'),
        ('video', '视频'),
    ]

    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='medias',
        verbose_name="帖子"
    )
    media_type = models.CharField(
        max_length=10,
        choices=MEDIA_TYPE_CHOICES,
        verbose_name="媒体类型"
    )
    url = models.URLField(max_length=500, verbose_name="文件URL")
    thumbnail_url = models.URLField(max_length=500, blank=True, default="", verbose_name="缩略图URL")
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name="排序")
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="宽度")
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="高度")
    duration = models.PositiveIntegerField(null=True, blank=True, verbose_name="时长(秒)")
    file_size = models.PositiveIntegerField(null=True, blank=True, verbose_name="文件大小(字节)")

    class Meta:
        db_table = 'post_medias'
        verbose_name = '帖子媒体'
        verbose_name_plural = '帖子媒体'
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['post', 'media_type']),
        ]


class Comment(BaseModel):
    """评论"""
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='comments',
        db_index=True,
        verbose_name="帖子"
    )
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_index=True,
        verbose_name="评论者"
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
        verbose_name="父评论"
    )

    # 评论内容
    content = models.TextField(verbose_name="评论内容")

    # 互动统计
    like_count = models.PositiveIntegerField(default=0, db_index=True, verbose_name="点赞数")
    reply_count = models.PositiveIntegerField(default=0, verbose_name="回复数")

    # 标识
    is_author_reply = models.BooleanField(default=False, verbose_name="是否作者回复")
    is_featured = models.BooleanField(default=False, db_index=True, verbose_name="是否精选评论")
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name="是否删除")

    # IP地址记录
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP地址")
    location = models.CharField(max_length=50, blank=True, default="", verbose_name="发布位置")

    class Meta:
        db_table = 'comments'
        verbose_name = '评论'
        verbose_name_plural = '评论'
        ordering = ['-is_featured', '-like_count', '-created_at']
        indexes = [
            models.Index(fields=['post', 'is_deleted', '-created_at']),
            models.Index(fields=['author', '-created_at']),
            models.Index(fields=['parent', '-created_at']),
        ]

    def __str__(self):
        return f"{self.author.username}: {self.content[:30]}..."


class Topic(BaseModel):
    """话题"""

    STATUS_CHOICES = [
        ('pending', '待审核'),
        ('reviewing', '审核中'),
        ('approved', '审核通过'),
        ('rejected', '审核拒绝'),
        ('banned', '已封禁'),
        ('suspended', '已暂停'),
    ]

    name = models.CharField(max_length=50, unique=True, verbose_name="话题名称")
    slug = models.SlugField(max_length=50, unique=True, verbose_name="URL标识")
    description = models.CharField(max_length=200, blank=True, default="", verbose_name="话题描述")
    cover_image = models.URLField(max_length=500, blank=True, default="", verbose_name="话题封面")

    # 创建者信息
    creator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="创建者"
    )

    # 话题属性
    is_official = models.BooleanField(default=False, db_index=True, verbose_name="是否官方话题")
    is_trending = models.BooleanField(default=False, db_index=True, verbose_name="是否热门")
    is_featured = models.BooleanField(default=False, db_index=True, verbose_name="是否精选话题")

    # 审核状态
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name="审核状态"
    )

    # 审核信息
    reviewer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_topics',
        verbose_name="审核人"
    )
    review_note = models.TextField(blank=True, default="", verbose_name="审核备注")
    reject_reason = models.CharField(max_length=200, blank=True, default="", verbose_name="拒绝原因")
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")

    # 统计数据
    post_count = models.PositiveIntegerField(default=0, db_index=True, verbose_name="帖子数量")
    participant_count = models.PositiveIntegerField(default=0, verbose_name="参与人数")
    follow_count = models.PositiveIntegerField(default=0, db_index=True, verbose_name="关注数量")
    view_count = models.PositiveBigIntegerField(default=0, verbose_name="浏览量")

    # 热度计算
    hot_score = models.FloatField(default=0, db_index=True, verbose_name="热度分数")

    # 举报相关
    report_count = models.PositiveSmallIntegerField(default=0, verbose_name="举报次数")

    class Meta:
        db_table = 'topics'
        verbose_name = '话题'
        verbose_name_plural = '话题'
        ordering = ['-is_featured', '-hot_score', '-post_count']
        indexes = [
            models.Index(fields=['status', '-hot_score']),
            models.Index(fields=['creator', 'status']),
            models.Index(fields=['is_trending', '-updated_at']),
        ]

    def __str__(self):
        return f"#{self.name}"

    @property
    def can_be_used(self):
        """判断话题是否可以使用"""
        return self.status == 'approved'


class UserAction(BaseModel):
    """用户行为记录"""

    ACTION_TYPE_CHOICES = [
        ('like_post', '点赞帖子'),
        ('unlike_post', '取消点赞帖子'),
        ('collect_post', '收藏帖子'),
        ('uncollect_post', '取消收藏帖子'),
        ('share_post', '分享帖子'),
        ('view_post', '浏览帖子'),
        ('comment_post', '评论帖子'),
        ('like_comment', '点赞评论'),
        ('unlike_comment', '取消点赞评论'),
        ('follow_user', '关注用户'),
        ('unfollow_user', '取消关注用户'),
        ('follow_topic', '关注话题'),
        ('unfollow_topic', '取消关注话题'),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_index=True,
        verbose_name="用户"
    )
    action_type = models.CharField(
        max_length=20,
        choices=ACTION_TYPE_CHOICES,
        db_index=True,
        verbose_name="行为类型"
    )

    # 关联对象（使用ContentType更灵活，但这里简化处理）
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="帖子"
    )
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="评论"
    )
    target_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='follower_actions',
        verbose_name="目标用户"
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="话题"
    )

    # 额外信息
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP地址")
    user_agent = models.CharField(max_length=200, blank=True, default="", verbose_name="用户代理")

    class Meta:
        db_table = 'user_actions'
        verbose_name = '用户行为'
        verbose_name_plural = '用户行为'
        indexes = [
            models.Index(fields=['user', 'action_type', '-created_at']),
            models.Index(fields=['post', 'action_type']),
            models.Index(fields=['target_user', 'action_type']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'post'],
                condition=models.Q(action_type='like_post'),
                name='unique_post_like'
            ),
            models.UniqueConstraint(
                fields=['user', 'post'],
                condition=models.Q(action_type='collect_post'),
                name='unique_post_collect'
            ),
            models.UniqueConstraint(
                fields=['user', 'comment'],
                condition=models.Q(action_type='like_comment'),
                name='unique_comment_like'
            ),
            models.UniqueConstraint(
                fields=['user', 'target_user'],
                condition=models.Q(action_type='follow_user'),
                name='unique_user_follow'
            ),
            models.UniqueConstraint(
                fields=['user', 'topic'],
                condition=models.Q(action_type='follow_topic'),
                name='unique_topic_follow'
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - {dict(self.ACTION_TYPE_CHOICES)[self.action_type]}"


class ReviewLog(BaseModel):
    """统一的审核日志"""

    CONTENT_TYPE_CHOICES = [
        ('post', '帖子'),
        ('topic', '话题'),
        ('comment', '评论'),
    ]

    ACTION_CHOICES = [
        ('submit', '提交审核'),
        ('auto_approve', '自动通过'),
        ('auto_reject', '自动拒绝'),
        ('manual_approve', '人工通过'),
        ('manual_reject', '人工拒绝'),
        ('hide', '隐藏'),
        ('ban', '封禁'),
        ('restore', '恢复'),
    ]

    content_type = models.CharField(
        max_length=20,
        choices=CONTENT_TYPE_CHOICES,
        db_index=True,
        verbose_name="内容类型"
    )
    content_id = models.PositiveIntegerField(db_index=True, verbose_name="内容ID")

    reviewer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        verbose_name="审核人"
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        verbose_name="审核动作"
    )
    reason = models.CharField(max_length=200, blank=True, default="", verbose_name="操作原因")
    note = models.TextField(blank=True, default="", verbose_name="审核备注")

    # 审核前后状态
    old_status = models.CharField(max_length=20, blank=True, default="", verbose_name="原状态")
    new_status = models.CharField(max_length=20, blank=True, default="", verbose_name="新状态")

    # 违规信息
    violation_details = models.JSONField(default=dict, blank=True, verbose_name="违规详情")

    class Meta:
        db_table = 'review_logs'
        verbose_name = '审核日志'
        verbose_name_plural = '审核日志'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'content_id', '-created_at']),
            models.Index(fields=['reviewer', '-created_at']),
        ]


class SensitiveWord(BaseModel):
    """敏感词库"""

    WORD_TYPE_CHOICES = [
        ('banned', '禁用词'),
        ('sensitive', '敏感词'),
        ('review', '需审核词'),
    ]

    CATEGORY_CHOICES = [
        ('politics', '政治'),
        ('porn', '色情'),
        ('violence', '暴力'),
        ('abuse', '辱骂'),
        ('ad', '广告'),
        ('other', '其他'),
    ]

    word = models.CharField(max_length=100, unique=True, db_index=True, verbose_name="敏感词")
    word_type = models.CharField(
        max_length=20,
        choices=WORD_TYPE_CHOICES,
        db_index=True,
        verbose_name="词汇类型"
    )
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default='other',
        verbose_name="分类"
    )
    replacement = models.CharField(max_length=50, blank=True, default="***", verbose_name="替换词")
    severity = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name="严重程度"
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="是否启用")
    hit_count = models.PositiveIntegerField(default=0, verbose_name="命中次数")

    class Meta:
        db_table = 'sensitive_words'
        verbose_name = '敏感词'
        verbose_name_plural = '敏感词'
        indexes = [
            models.Index(fields=['word_type', 'is_active']),
        ]

    def __str__(self):
        return f"{self.word} ({dict(self.WORD_TYPE_CHOICES)[self.word_type]})"


class Report(BaseModel):
    """举报记录"""

    REPORT_TYPE_CHOICES = [
        ('spam', '垃圾广告'),
        ('porn', '色情低俗'),
        ('violence', '暴力血腥'),
        ('fraud', '欺诈骗局'),
        ('abuse', '辱骂攻击'),
        ('copyright', '侵权'),
        ('false_info', '虚假信息'),
        ('other', '其他'),
    ]

    CONTENT_TYPE_CHOICES = [
        ('post', '帖子'),
        ('comment', '评论'),
        ('user', '用户'),
        ('topic', '话题'),
    ]

    STATUS_CHOICES = [
        ('pending', '待处理'),
        ('processing', '处理中'),
        ('resolved', '已处理'),
        ('rejected', '已驳回'),
        ('ignored', '已忽略'),
    ]

    reporter = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reports_made',
        verbose_name="举报人"
    )

    content_type = models.CharField(
        max_length=20,
        choices=CONTENT_TYPE_CHOICES,
        db_index=True,
        verbose_name="内容类型"
    )
    content_id = models.PositiveIntegerField(db_index=True, verbose_name="内容ID")

    report_type = models.CharField(
        max_length=20,
        choices=REPORT_TYPE_CHOICES,
        db_index=True,
        verbose_name="举报类型"
    )
    reason = models.TextField(verbose_name="举报理由")
    evidence = models.JSONField(default=list, blank=True, verbose_name="证据材料")

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name="处理状态"
    )

    handler = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reports_handled',
        verbose_name="处理人"
    )
    handle_note = models.TextField(blank=True, default="", verbose_name="处理备注")
    handled_at = models.DateTimeField(null=True, blank=True, verbose_name="处理时间")

    # IP记录
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="举报人IP")

    class Meta:
        db_table = 'reports'
        verbose_name = '举报记录'
        verbose_name_plural = '举报记录'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['content_type', 'content_id']),
            models.Index(fields=['reporter', '-created_at']),
        ]
        constraints = [
            # 防止重复举报
            models.UniqueConstraint(
                fields=['reporter', 'content_type', 'content_id'],
                name='unique_report_per_content'
            )
        ]

    def __str__(self):
        return f"{self.reporter.username} 举报 {dict(self.CONTENT_TYPE_CHOICES)[self.content_type]}"


class Notification(BaseModel):
    """通知消息"""

    NOTIFICATION_TYPE_CHOICES = [
        ('like_post', '点赞了你的帖子'),
        ('comment_post', '评论了你的帖子'),
        ('reply_comment', '回复了你的评论'),
        ('follow_user', '关注了你'),
        ('mention', '提到了你'),
        ('system', '系统通知'),
        ('post_featured', '帖子被精选'),
        ('post_approved', '帖子审核通过'),
        ('post_rejected', '帖子审核未通过'),
    ]

    receiver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        db_index=True,
        verbose_name="接收者"
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='sent_notifications',
        verbose_name="发送者"
    )

    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPE_CHOICES,
        db_index=True,
        verbose_name="通知类型"
    )

    # 关联内容
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="相关帖子"
    )
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name="相关评论"
    )

    # 通知内容
    title = models.CharField(max_length=100, verbose_name="标题")
    content = models.CharField(max_length=200, verbose_name="内容")
    extra_data = models.JSONField(default=dict, blank=True, verbose_name="额外数据")

    # 状态
    is_read = models.BooleanField(default=False, db_index=True, verbose_name="是否已读")
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="阅读时间")

    class Meta:
        db_table = 'notifications'
        verbose_name = '通知消息'
        verbose_name_plural = '通知消息'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['receiver', 'is_read', '-created_at']),
            models.Index(fields=['notification_type', '-created_at']),
        ]

    def __str__(self):
        return f"{self.receiver.username} - {self.title}"

    def mark_as_read(self):
        """标记为已读"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])


class PostView(BaseModel):
    """帖子浏览记录（用于统计和推荐）"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        db_index=True,
        verbose_name="用户"
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        db_index=True,
        verbose_name="帖子"
    )
    view_count = models.PositiveSmallIntegerField(default=1, verbose_name="浏览次数")
    duration = models.PositiveIntegerField(default=0, verbose_name="停留时长(秒)")
    source = models.CharField(max_length=30, blank=True, default="", verbose_name="来源")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP地址")

    class Meta:
        db_table = 'post_views'
        verbose_name = '帖子浏览记录'
        verbose_name_plural = '帖子浏览记录'
        indexes = [
            models.Index(fields=['user', 'post']),
            models.Index(fields=['post', '-created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'post'],
                name='unique_user_post_view'
            )
        ]


class UserFollow(BaseModel):
    """用户关注关系"""
    follower = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='following',
        db_index=True,
        verbose_name="关注者"
    )
    following = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='followers',
        db_index=True,
        verbose_name="被关注者"
    )
    is_mutual = models.BooleanField(default=False, db_index=True, verbose_name="是否互相关注")

    class Meta:
        db_table = 'user_follows'
        verbose_name = '用户关注'
        verbose_name_plural = '用户关注'
        constraints = [
            models.UniqueConstraint(
                fields=['follower', 'following'],
                name='unique_follow_relation'
            ),
            models.CheckConstraint(
                check=~models.Q(follower=models.F('following')),
                name='prevent_self_follow'
            )
        ]
        indexes = [
            models.Index(fields=['follower', '-created_at']),
            models.Index(fields=['following', '-created_at']),
            models.Index(fields=['is_mutual']),
        ]

    def save(self, *args, **kwargs):
        # 检查是否互相关注
        reverse_follow = UserFollow.objects.filter(
            follower=self.following,
            following=self.follower
        ).first()
        if reverse_follow:
            self.is_mutual = True
            reverse_follow.is_mutual = True
            reverse_follow.save(update_fields=['is_mutual'])
        super().save(*args, **kwargs)


class PostCollection(BaseModel):
    """帖子收藏"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='collections',
        db_index=True,
        verbose_name="用户"
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name='collectors',
        db_index=True,
        verbose_name="帖子"
    )
    folder = models.CharField(max_length=50, blank=True, default="默认收藏夹", verbose_name="收藏夹")
    note = models.CharField(max_length=200, blank=True, default="", verbose_name="备注")

    class Meta:
        db_table = 'post_collections'
        verbose_name = '帖子收藏'
        verbose_name_plural = '帖子收藏'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'post'],
                name='unique_post_collection'
            )
        ]
        indexes = [
            models.Index(fields=['user', 'folder', '-created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} 收藏 {self.post.title}"


class BlockedUser(BaseModel):
    """用户黑名单"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='blocked_users',
        verbose_name="用户"
    )
    blocked_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='blocked_by',
        verbose_name="被拉黑用户"
    )
    reason = models.CharField(max_length=100, blank=True, default="", verbose_name="拉黑原因")

    class Meta:
        db_table = 'blocked_users'
        verbose_name = '用户黑名单'
        verbose_name_plural = '用户黑名单'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'blocked_user'],
                name='unique_block_relation'
            ),
            models.CheckConstraint(
                check=~models.Q(user=models.F('blocked_user')),
                name='prevent_self_block'
            )
        ]

    def __str__(self):
        return f"{self.user.username} 拉黑 {self.blocked_user.username}"