# -*- coding: utf-8 -*-
# @Time    : 2025/8/23 15:35
# @Author  : Delock

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# 创建路由器
router = DefaultRouter()

# 注册ViewSets
router.register(r'users', views.UserViewSet, basename='user')
router.register(r'categories', views.PostCategoryViewSet, basename='category')
router.register(r'topics', views.TopicViewSet, basename='topic')
router.register(r'posts', views.PostViewSet, basename='post')
router.register(r'comments', views.CommentViewSet, basename='comment')
router.register(r'actions', views.UserActionViewSet, basename='action')
router.register(r'notifications', views.NotificationViewSet, basename='notification')
router.register(r'reports', views.ReportViewSet, basename='report')
router.register(r'community', views.PetCommunityViewSet, basename='community')

# 管理员路由器
admin_router = DefaultRouter()
admin_router.register(r'posts', views.AdminPostViewSet, basename='admin-post')


# ==================== URL配置 ====================

urlpatterns = [
    # ========== ViewSet路由（自动生成标准REST接口）==========
    path('', include(router.urls)),

    # ========== 管理员路由 ==========
    path('admin/', include(admin_router.urls)),

    # ========== 独立API端点 ==========
    path('search/', views.SearchView.as_view(), name='search'),
    path('statistics/', views.StatisticsView.as_view(), name='statistics'),
    path('realtime/', views.RealtimeView.as_view(), name='realtime'),

    # ========== 页面路由（前端路由,如果需要）==========
    path('', include([
        # 首页
        path('', views.PetCommunityViewSet.as_view({'get': 'list'}), name='home'),

        # 宠物社区特色功能
        path('home-posts/', views.PetCommunityViewSet.as_view({'get': 'home_posts'}), name='community-home-posts'),
        path('tips/', views.PetCommunityViewSet.as_view({'get': 'pet_care_tips'}), name='pet-care-tips'),
        path('adoption/', views.PetCommunityViewSet.as_view({'get': 'pet_adoption'}), name='pet-adoption'),

        # 用户相关页面
        path('users/<str:username>/', views.UserViewSet.as_view({'get': 'retrieve'}), name='user-profile'),
        path('users/<str:username>/posts/', views.UserViewSet.as_view({'get': 'posts'}), name='user-posts'),
        path('users/<str:username>/collections/', views.UserViewSet.as_view({'get': 'collections'}),
             name='user-collections'),

        # 帖子相关页面
        path('posts/', views.PostViewSet.as_view({'get': 'list'}), name='post-list'),
        path('posts/<int:pk>/', views.PostViewSet.as_view({'get': 'retrieve'}), name='post-detail'),
        path('posts/create/', views.PostViewSet.as_view({'post': 'create'}), name='post-create'),
        path('posts/trending/', views.PostViewSet.as_view({'get': 'trending'}), name='post-trending'),
        path('posts/feed/', views.PostViewSet.as_view({'get': 'feed'}), name='post-feed'),
        path('my-posts/', views.PostViewSet.as_view({'get': 'my_posts'}), name='my-posts'),

        # 分类相关页面
        path('categories/', views.PostCategoryViewSet.as_view({'get': 'list'}), name='category-list'),
        path('categories/<int:pk>/', views.PostCategoryViewSet.as_view({'get': 'retrieve'}), name='category-detail'),
        path('categories/<int:pk>/posts/', views.PostCategoryViewSet.as_view({'get': 'posts'}), name='category-posts'),

        # 话题相关页面
        path('topics/', views.TopicViewSet.as_view({'get': 'list'}), name='topic-list'),
        path('topics/<slug:slug>/', views.TopicViewSet.as_view({'get': 'retrieve'}), name='topic-detail'),
        path('topics/<slug:slug>/posts/', views.TopicViewSet.as_view({'get': 'posts'}), name='topic-posts'),

        # 搜索页面
        path('search/', views.SearchView.as_view(), name='search'),

        # 通知页面
        path('notifications/', views.NotificationViewSet.as_view({'get': 'list'}), name='notification-list'),

        # 统计页面
        path('stats/', views.StatisticsView.as_view(), name='statistics'),
    ])),
]