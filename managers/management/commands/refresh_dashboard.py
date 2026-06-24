# -*- coding: utf-8 -*-
# @Time    : 2026/6/24 15:07
# @Author  : Delock


from django.core.management.base import BaseCommand

from managers.dashboard_stats import refresh_dashboard_cache


class Command(BaseCommand):
    help = '聚合管理端数据面板指标并写入 Redis (建议每天定时执行一次)'

    def handle(self, *args, **options):
        data = refresh_dashboard_cache()
        self.stdout.write(self.style.SUCCESS(
            f"✓ 数据面板已刷新 @ {data['generated_at']}"
        ))