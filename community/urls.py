# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# ==================== 路由器注册 ====================
router = DefaultRouter()
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'categories', views.PostCategoryViewSet, basename='category')
router.register(r'topics', views.TopicViewSet, basename='topic')
router.register(r'posts', views.PostViewSet, basename='post')
router.register(r'comments', views.CommentViewSet, basename='comment')
router.register(r'actions', views.UserActionViewSet, basename='action')
router.register(r'notifications', views.NotificationViewSet, basename='notification')
router.register(r'reports', views.ReportViewSet, basename='report')
router.register(r'history', views.PostHistoryViewSet, basename='history')
# 注意：PetCommunityViewSet 不注册到 router，避免 community/community/ 双重前缀
#       改用下方独立路径挂载

# 管理员路由器
admin_router = DefaultRouter()
admin_router.register(r'posts', views.AdminPostViewSet, basename='admin-post')
admin_router.register(r'reports', views.AdminReportViewSet, basename='admin-report')

admin_router.register(r'categories', views.AdminPostCategoryViewSet, basename='admin-category')

# ==================== URL 配置 ====================
# 整体挂载在 community/ 下
# 主 urls.py: path('api/v1/', include('community.urls'))
# 最终基路径: /api/v1/community/

urlpatterns = [
    path('community/', include([

        # ===== ViewSet 路由（DRF Router 自动生成）=====
        path('', include(router.urls)),

        # ===== 管理员路由 =====
        path('admin/', include(admin_router.urls)),

        # ===== 宠物社区首页（独立路径，避免 community/community/）=====
        path('home/',
             views.PetCommunityViewSet.as_view({'get': 'list'}),
             name='community-home'),
        path('home-posts/',
             views.PetCommunityViewSet.as_view({'get': 'home_posts'}),
             name='community-home-posts'),
        path('tips/',
             views.PetCommunityViewSet.as_view({'get': 'pet_care_tips'}),
             name='pet-care-tips'),
        path('adoption/',
             views.PetCommunityViewSet.as_view({'get': 'pet_adoption'}),
             name='pet-adoption'),

        # ===== 独立 API 端点 =====
        path('search/',
             views.SearchView.as_view(),
             name='search'),
        path('sensitive-check/',
             views.SensitiveWordCheckView.as_view(),
             name='sensitive-check'),
        path('statistics/',
             views.StatisticsView.as_view(),
             name='statistics'),
        path('realtime/',
             views.RealtimeView.as_view(),
             name='realtime'),
        path('content-data/',
             views.ContentDataView.as_view(),
             name='content-data'),
    ])),
]