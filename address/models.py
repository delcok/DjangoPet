from django.db import models


class UserAddress(models.Model):
    """用户收货地址"""

    class AddressType(models.TextChoices):
        COMMUNITY = 'community', '小区住宅'
        STREET = 'street', '街道/其他'

    user = models.ForeignKey(
        'user.User',
        on_delete=models.CASCADE,
        related_name='addresses',
        verbose_name='用户'
    )
    receiver_name = models.CharField(
        max_length=30, verbose_name='收货人姓名'
    )
    receiver_phone = models.CharField(
        max_length=17, verbose_name='收货人电话'
    )

    # ══════ 地址模式 ══════
    address_type = models.CharField(
        max_length=20,
        choices=AddressType.choices,
        default=AddressType.COMMUNITY,
        verbose_name='地址类型',
        help_text='community=小区楼栋模式, street=街道门牌模式'
    )

    # ══════ 省市区（当前可为空，全国化时启用）══════
    province = models.CharField(
        max_length=20, blank=True, default='',
        db_index=True, verbose_name='省'
    )
    city = models.CharField(
        max_length=20, blank=True, default='',
        db_index=True, verbose_name='市'
    )
    district = models.CharField(
        max_length=20, blank=True, default='',
        db_index=True, verbose_name='区'
    )

    # ══════ 社区模式字段 ══════
    community = models.CharField(
        max_length=100, blank=True, default='',
        db_index=True, verbose_name='小区/社区',
        help_text='如：阳光花园、万科城市花园'
    )
    building = models.CharField(
        max_length=30, blank=True, default='',
        verbose_name='楼栋',
        help_text='如：3栋、A座、5号楼'
    )
    unit = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name='单元',
        help_text='如：2单元，无单元可留空'
    )
    room = models.CharField(
        max_length=30, blank=True, default='',
        verbose_name='门牌号',
        help_text='如：1201、3-502'
    )

    # ══════ 街道模式字段 ══════
    street = models.CharField(
        max_length=200, blank=True, default='',
        verbose_name='街道地址',
        help_text='街道模式时填写，如：建设路128号'
    )
    house_number = models.CharField(
        max_length=50, blank=True, default='',
        verbose_name='门牌/房号',
        help_text='街道模式的门牌，如：3层302室'
    )

    # ══════ 兼容字段（自动拼接，保持向后兼容）══════
    detail_address = models.CharField(
        max_length=200, verbose_name='详细地址',
        help_text='由结构化字段自动拼接，也可直接填写'
    )

    # ══════ 坐标 ══════
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True, verbose_name='经度'
    )
    latitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True, verbose_name='纬度'
    )

    access_instructions = models.TextField(
        blank=True, default='',
        verbose_name='入户说明',
        help_text='如：到小区门口打电话、放门卫处'
    )

    # ══════ 标记 ══════
    is_default = models.BooleanField(default=False, verbose_name='默认地址')
    tag = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name='地址标签',
        help_text='如 家 / 公司 / 学校'
    )

    # ══════ 时间戳 ══════
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        db_table = 'user_addresses'
        verbose_name = '用户地址'
        verbose_name_plural = '用户地址'
        indexes = [
            models.Index(fields=['user', 'is_default']),
            models.Index(fields=['community']),
        ]

    def __str__(self):
        return f"{self.receiver_name} - {self.short_address}"

    def save(self, *args, **kwargs):
        """保存时自动拼接 detail_address（如果结构化字段有值）"""
        composed = self._compose_detail()
        if composed:
            self.detail_address = composed
        super().save(*args, **kwargs)

    def _compose_detail(self) -> str:
        """根据地址类型拼接详细地址"""
        if self.address_type == self.AddressType.COMMUNITY:
            parts = []
            if self.community:
                parts.append(self.community)
            if self.building:
                parts.append(self.building)
            if self.unit:
                parts.append(self.unit)
            if self.room:
                parts.append(self.room)
            return ''.join(parts) if parts else ''

        elif self.address_type == self.AddressType.STREET:
            parts = []
            if self.street:
                parts.append(self.street)
            if self.house_number:
                parts.append(self.house_number)
            return ''.join(parts) if parts else ''

        return ''

    @property
    def full_address(self) -> str:
        """完整地址（含省市区，全国化后使用）"""
        prefix = f"{self.province}{self.city}{self.district}"
        return f"{prefix}{self.detail_address}" if prefix else self.detail_address

    @property
    def short_address(self) -> str:
        """短地址（当前社区级展示用）"""
        if self.address_type == self.AddressType.COMMUNITY:
            parts = [self.community, self.building, self.unit, self.room]
            return ' '.join(p for p in parts if p)
        return self.detail_address or ''

    @property
    def service_address(self) -> str:
        """
        上门服务地址（给服务人员/骑手看的，含户号）
        社区模式: 阳光花园 3栋2单元1201
        街道模式: 建设路128号3层302室
        """
        if self.address_type == self.AddressType.COMMUNITY:
            parts = [self.community, self.building, self.unit, self.room]
            return ' '.join(p for p in parts if p)
        parts = [self.street, self.house_number]
        return ' '.join(p for p in parts if p) or self.detail_address or ''