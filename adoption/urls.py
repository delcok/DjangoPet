# -*- coding: utf-8 -*-
# @Time    : 2026/6/7 16:33
# @Author  : Delock


# -*- coding: utf-8 -*-
"""
adoption/urls.py — 领养模块路由

项目根 urls.py 挂载:
    path('api/v1/', include('adoption.urls'))
本文件内部统一带 adoption/ 前缀,最终完整路径为 /api/v1/adoption/...
(与前端 adoption.js 的 PREFIX = '/adoption' 严格对应)

═══════════════════ 端点速查 ═══════════════════
【C端 - 小程序】
GET    /api/v1/adoption/pets/                        宠物列表(?species=cat,dog&city=&has_quota=true&keyword=&ordering=-favorite_count)
GET    /api/v1/adoption/pets/{id}/                   宠物详情(浏览量+1;登录态含 is_favorited/my_application)
POST   /api/v1/adoption/pets/{id}/favorite/          收藏
DELETE /api/v1/adoption/pets/{id}/favorite/          取消收藏
GET    /api/v1/adoption/pets/{id}/updates/           "领养后的TA"公开动态流(游标分页 ?cursor=)
POST   /api/v1/adoption/applications/                提交领养申请
GET    /api/v1/adoption/applications/?status=        我的申请列表
GET    /api/v1/adoption/applications/{id}/           我的申请详情(时间线+打卡任务)
POST   /api/v1/adoption/applications/{id}/cancel/    取消申请(approved 后不可自助取消)
POST   /api/v1/adoption/updates/                     提交打卡动态(带 task)/自主加更(不带 task)
GET    /api/v1/adoption/updates/                     我发布的动态
GET    /api/v1/adoption/my/update-tasks/?status=pending  我的打卡任务
GET    /api/v1/adoption/my/favorites/                我的收藏
GET    /api/v1/adoption/my/profile/                  我的领养资格

【后台 - 平台管理员】
GET/POST          /api/v1/adoption/admin/pets/                  宠物列表/登记
GET/PATCH/DELETE  /api/v1/adoption/admin/pets/{id}/             详情/编辑(含上下架)/软删
POST              /api/v1/adoption/admin/pets/{id}/add_media/   追加图片视频
DELETE            /api/v1/adoption/admin/pets/{id}/media/{mid}/ 删除图片视频
GET               /api/v1/adoption/admin/applications/?pet=&status=&ordering=-review_score  申请列表(同宠物对比择优)
GET               /api/v1/adoption/admin/applications/{id}/     申请详情(完整资料+日志)
POST              /api/v1/adoption/admin/applications/{id}/action/  审核流转
                  body: {"action": "start_review|to_interview|approve|reject|complete|returned",
                         "review_score": 90, "review_note": "", "reject_reason": "", "agreement_url": "", "remark": ""}
GET               /api/v1/adoption/admin/update-tasks/?status=overdue  打卡逾期看板
POST              /api/v1/adoption/admin/update-tasks/{id}/exempt/     豁免该期
GET/POST          /api/v1/adoption/admin/updates/               动态审查队列 / 回访代录
POST              /api/v1/adoption/admin/updates/{id}/review/   动态结论 {"review_status": "normal|abnormal"}
GET/POST          /api/v1/adoption/admin/violations/            违规记录(创建即联动资格处罚)
GET/PATCH         /api/v1/adoption/admin/profiles/              资格档案(手动解禁/封禁/备注)
═══════════════════════════════════════════════
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'adoption'

router = DefaultRouter()
# ---- C端 ----
router.register(r'pets', views.StrayPetViewSet, basename='pet')
router.register(r'applications', views.MyApplicationViewSet, basename='my-application')
router.register(r'updates', views.MyUpdateViewSet, basename='my-update')
# ---- 后台 ----
router.register(r'admin/pets', views.AdminPetViewSet, basename='admin-pet')
router.register(r'admin/applications', views.AdminApplicationViewSet, basename='admin-application')
router.register(r'admin/update-tasks', views.AdminUpdateTaskViewSet, basename='admin-update-task')
router.register(r'admin/updates', views.AdminUpdateViewSet, basename='admin-update')
router.register(r'admin/violations', views.AdminViolationViewSet, basename='admin-violation')
router.register(r'admin/profiles', views.AdminAdopterProfileViewSet, basename='admin-adopter-profile')

urlpatterns = [
    # 注意: 固定路径放 router 之前,避免被 ViewSet 的 detail 路由抢先匹配
    path('adoption/my/update-tasks/', views.MyUpdateTaskListView.as_view(), name='my-update-tasks'),
    path('adoption/my/favorites/', views.MyFavoriteListView.as_view(), name='my-favorites'),
    path('adoption/my/profile/', views.MyAdopterProfileView.as_view(), name='my-adopter-profile'),
    path('adoption/', include(router.urls)),
]