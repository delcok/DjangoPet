from django.db import models


class HomepagePosition(models.Model):
    """
    首页推荐位 —— 社区优惠、超级推荐、特价团。
    支持商品和服务混排，展示信息直接取原对象。
    """

    class Position(models.TextChoices):
        COMMUNITY_DISCOUNT = 'community_discount', '社区优惠'
        SUPER_RECOMMEND = 'super_recommend', '超级推荐'
        SPECIAL_GROUP = 'bargain', '特价'

    class TargetType(models.TextChoices):
        GOODS = 'goods', '商品'
        SERVICE = 'service', '服务'

    position = models.CharField(
        max_length=30,
        choices=Position.choices,
        db_index=True,
        verbose_name='推荐板块',
    )
    target_type = models.CharField(
        max_length=20,
        choices=TargetType.choices,
        verbose_name='目标类型',
    )
    target_id = models.PositiveIntegerField(verbose_name='目标ID')

    sort_order = models.IntegerField(default=0, verbose_name='排序权重')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'homepage_position'
        verbose_name = '首页推荐位'
        verbose_name_plural = verbose_name
        ordering = ['-sort_order', '-id']
        unique_together = ['position', 'target_type', 'target_id']
        indexes = [
            models.Index(fields=['position', 'is_active', 'sort_order']),
        ]

    def __str__(self):
        return f'{self.get_position_display()} - {self.get_target_type_display()}#{self.target_id}'


class HomepageSection(models.Model):
    """
    首页板块配置 —— 三块固定区域(社区优惠/超级推荐/特价)的可编辑标题。
    每个 position 一条记录,固定 3 行。与 HomepagePosition 通过 position 值逻辑对齐,无外键。
    """

    DEFAULTS = {
        HomepagePosition.Position.COMMUNITY_DISCOUNT: ('社区优惠', '低价好服务 限时抢'),
        HomepagePosition.Position.SUPER_RECOMMEND:    ('超级推荐', '小二力荐 不容错过'),
        HomepagePosition.Position.SPECIAL_GROUP:      ('特价团', '天天低价 抢到就赚'),
    }

    position = models.CharField(
        max_length=30,
        choices=HomepagePosition.Position.choices,
        unique=True,
        verbose_name='板块',
    )
    title = models.CharField(max_length=50, verbose_name='板块标题')
    subtitle = models.CharField(max_length=100, blank=True, default='', verbose_name='副标题')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'homepage_section'
        verbose_name = '首页板块配置'
        verbose_name_plural = verbose_name
        ordering = ['id']

    def __str__(self):
        return f'{self.position} - {self.title}'

    @classmethod
    def ensure_defaults(cls):
        """保证三块区域各有一条记录,缺了就按默认值补上(幂等)"""
        for pos, (title, subtitle) in cls.DEFAULTS.items():
            cls.objects.get_or_create(
                position=pos,
                defaults={'title': title, 'subtitle': subtitle},
            )