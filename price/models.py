from django.db import models


class Service(models.Model):
    name = models.CharField(max_length=100, verbose_name="服务名称")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="价格")
    description = models.TextField(verbose_name="服务描述")
    service_process = models.TextField(verbose_name="服务流程")

    # 服务属性
    duration = models.IntegerField(verbose_name="基础服务时长(分钟)")
    is_door_to_door = models.BooleanField(default=True, verbose_name="是否上门服务")

    # 服务要求和注意事项
    requirements = models.TextField(blank=True, null=True, verbose_name="服务要求")
    precautions = models.TextField(blank=True, null=True, verbose_name="注意事项")



