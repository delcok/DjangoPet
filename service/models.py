from django.db import models

class ServiceModel(models.Model):
    name = models.CharField(max_length=50, verbose_name='服务类型')
    base_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='基础价格')
    created_at = models.DateTimeField(auto_now_add=True)


# 宠物类型选择
class PetType(models.Model):
    name = models.CharField(max_length=50, verbose_name='宠物类型')  # 猫、狗、兔子等
    base_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='基础上门价格')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '宠物类型'
        verbose_name_plural = '宠物类型'

    def __str__(self):
        return self.name


class AdditionalService(models.Model):
    name = models.CharField(max_length=100, verbose_name='服务名称')
    description = models.TextField(blank=True, verbose_name='服务描述')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='服务价格')
    applicable_pets = models.ManyToManyField(PetType, verbose_name='适用宠物类型')
    is_active = models.BooleanField(default=True, verbose_name='是否启用')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '附加服务'
        verbose_name_plural = '附加服务'

    def __str__(self):
        return f"{self.name} - ¥{self.price}"



