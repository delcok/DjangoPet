# -*- coding: utf-8 -*-
# @Time    : 2025/8/23 15:35
# @Author  : Delock

from rest_framework.pagination import PageNumberPagination, CursorPagination
from rest_framework.response import Response
from collections import OrderedDict
from django.utils import timezone
import hashlib
import time


# ===== 基础分页类 =====
class BasePagination(PageNumberPagination):
    """基础分页类，提供通用功能"""

    def get_paginated_response(self, data):
        """统一的分页响应格式"""
        return Response(OrderedDict([
            ('success', True),
            ('code', 200),
            ('message', 'success'),
            ('data', OrderedDict([
                ('total', self.page.paginator.count),
                ('page', self.page.number),
                ('page_size', self.get_page_size(self.request)),
                ('total_pages', self.page.paginator.num_pages),
                ('has_next', self.page.has_next()),
                ('has_previous', self.page.has_previous()),
                ('next_page', self.page.next_page_number() if self.page.has_next() else None),
                ('prev_page', self.page.previous_page_number() if self.page.has_previous() else None),
                ('items', data)
            ]))
        ]))


class BaseCursorPagination(CursorPagination):
    """基础游标分页类"""

    def get_paginated_response(self, data):
        """统一的游标分页响应格式"""
        return Response(OrderedDict([
            ('success', True),
            ('code', 200),
            ('message', 'success'),
            ('data', OrderedDict([
                ('next_cursor', self.get_next_cursor()),
                ('prev_cursor', self.get_prev_cursor()),
                ('has_more', self.has_next),
                ('has_previous', self.has_previous),
                ('count', len(data)),
                ('items', data)
            ]))
        ]))

    def get_next_cursor(self):
        """获取下一页游标"""
        if self.has_next:
            return self.cursor.encode() if self.cursor else None
        return None

    def get_prev_cursor(self):
        """获取上一页游标"""
        if self.has_previous:
            return self.cursor.encode() if self.cursor else None
        return None


# ===== 标准分页类 =====
class StandardPagination(BasePagination):
    """标准分页 - 适用于大部分列表页面"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'


class SmallPagination(BasePagination):
    """小分页 - 适用于评论、回复等"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50
    page_query_param = 'page'


class LargePagination(BasePagination):
    """大分页 - 适用于搜索结果、数据导出等"""
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200
    page_query_param = 'page'


class MobilePagination(BasePagination):
    """移动端分页 - 较小的页面大小"""
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 30
    page_query_param = 'page'


# ===== 游标分页类 =====
class PostCursorPagination(BaseCursorPagination):
    """帖子游标分页 - 按发布时间排序"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = '-published_at'
    cursor_query_param = 'cursor'

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        # 添加帖子特定的元数据
        response.data['data']['feed_id'] = self.get_feed_id()
        response.data['data']['last_updated'] = timezone.now().isoformat()
        return response

    def get_feed_id(self):
        """生成Feed ID"""
        request = getattr(self, 'request', None)
        if request and request.user.is_authenticated:
            return f"feed_{request.user.id}_{int(time.time())}"
        return f"public_feed_{int(time.time())}"


class HotPostCursorPagination(BaseCursorPagination):
    """热门帖子游标分页 - 按热度排序"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = '-hot_score'
    cursor_query_param = 'cursor'

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data['data']['algorithm'] = 'hot_score'
        response.data['data']['score_range'] = self.get_score_range(data)
        return response

    def get_score_range(self, data):
        """获取当前页的分数范围"""
        if not data:
            return {'min': 0, 'max': 0}

        scores = []
        for item in data:
            if isinstance(item, dict) and 'hot_score' in item:
                scores.append(item['hot_score'])

        return {
            'min': min(scores) if scores else 0,
            'max': max(scores) if scores else 0
        }


class CommentCursorPagination(BaseCursorPagination):
    """评论游标分页 - 按时间排序"""
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 50
    ordering = '-created_at'
    cursor_query_param = 'cursor'


class NotificationCursorPagination(BaseCursorPagination):
    """通知游标分页 - 按时间排序"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = '-created_at'
    cursor_query_param = 'cursor'

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data['data']['unread_count'] = self.get_unread_count()
        return response

    def get_unread_count(self):
        """获取未读通知数量"""
        request = getattr(self, 'request', None)
        if request and request.user.is_authenticated:
            from .models import Notification
            return Notification.objects.filter(
                receiver=request.user,
                is_read=False
            ).count()
        return 0


# ===== 特殊分页类 =====
class SearchPagination(BasePagination):
    """搜索分页 - 包含搜索相关信息"""
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        request = getattr(self, 'request', None)

        # 添加搜索相关信息
        search_info = {
            'query': request.GET.get('q', '') if request else '',
            'search_time': timezone.now().isoformat(),
            'total_found': self.page.paginator.count,
            'search_suggestions': self.get_search_suggestions()
        }

        response.data['data']['search_info'] = search_info
        return response

    def get_search_suggestions(self):
        """获取搜索建议"""
        # 这里可以实现搜索建议逻辑
        return []


class FeedPagination(BaseCursorPagination):
    """Feed流分页 - 个性化推荐"""
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 50
    ordering = '-hot_score'
    cursor_query_param = 'cursor'

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)

        # 添加Feed特定信息
        feed_info = {
            'algorithm_version': 'v2.1',
            'personalization_level': self.get_personalization_level(),
            'refresh_token': self.generate_refresh_token(),
            'feed_type': 'recommended'
        }

        response.data['data']['feed_info'] = feed_info
        return response

    def get_personalization_level(self):
        """获取个性化程度"""
        request = getattr(self, 'request', None)
        if request and request.user.is_authenticated:
            # 根据用户活跃度等计算个性化程度
            return 'high'
        return 'low'

    def generate_refresh_token(self):
        """生成刷新令牌"""
        request = getattr(self, 'request', None)
        if request:
            token_string = f"{request.user.id if request.user.is_authenticated else 'anonymous'}_{int(time.time())}"
            return hashlib.md5(token_string.encode()).hexdigest()[:16]
        return None


class TrendingPagination(BasePagination):
    """趋势分页 - 热门趋势内容"""
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        request = getattr(self, 'request', None)

        # 添加趋势相关信息
        trending_info = {
            'period': request.GET.get('period', '24h') if request else '24h',
            'category': request.GET.get('category', 'all') if request else 'all',
            'updated_at': timezone.now().isoformat(),
            'next_update': self.get_next_update_time()
        }

        response.data['data']['trending_info'] = trending_info
        return response

    def get_next_update_time(self):
        """获取下次更新时间"""
        # 每小时更新一次趋势
        next_hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        next_hour = next_hour + timezone.timedelta(hours=1)
        return next_hour.isoformat()


class UserContentPagination(BasePagination):
    """用户内容分页 - 用户个人页面"""
    page_size = 12  # 网格布局友好的数字
    page_size_query_param = 'page_size'
    max_page_size = 60

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)

        # 添加用户相关统计
        user_stats = self.get_user_stats()
        response.data['data']['user_stats'] = user_stats
        return response

    def get_user_stats(self):
        """获取用户统计信息"""
        # 这里可以添加用户相关的统计信息
        return {
            'total_posts': self.page.paginator.count,
            'content_type': 'posts'
        }


class InfiniteScrollPagination(BaseCursorPagination):
    """无限滚动分页 - 移动端友好"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 30
    ordering = '-created_at'
    cursor_query_param = 'cursor'

    def get_paginated_response(self, data):
        """优化移动端的响应格式"""
        return Response(OrderedDict([
            ('success', True),
            ('has_more', self.has_next),
            ('next_cursor', self.get_next_cursor()),
            ('count', len(data)),
            ('items', data)
        ]))


# ===== 管理后台分页 =====
class AdminPagination(BasePagination):
    """管理后台分页"""
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 200

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)

        # 添加管理相关信息
        admin_info = {
            'view_type': 'admin',
            'export_available': True,
            'bulk_actions': ['approve', 'reject', 'delete'],
            'filters_applied': self.get_applied_filters()
        }

        response.data['data']['admin_info'] = admin_info
        return response

    def get_applied_filters(self):
        """获取已应用的过滤器"""
        request = getattr(self, 'request', None)
        if not request:
            return {}

        filters = {}
        for key, value in request.GET.items():
            if key not in ['page', 'page_size', 'cursor']:
                filters[key] = value

        return filters


class ReviewQueuePagination(BasePagination):
    """审核队列分页"""
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)

        # 添加审核队列统计
        queue_stats = self.get_queue_stats()
        response.data['data']['queue_stats'] = queue_stats
        return response

    def get_queue_stats(self):
        """获取审核队列统计"""
        from .models import Post, Topic, Comment

        return {
            'pending_posts': Post.objects.filter(status='pending').count(),
            'pending_topics': Topic.objects.filter(status='pending').count(),
            'review_priority_high': Post.objects.filter(
                status='pending',
                review_priority__gte=8
            ).count(),
            'auto_review_failed': Post.objects.filter(
                status='pending',
                auto_review_score__lt=60
            ).count()
        }


# ===== 分页类映射 =====
PAGINATION_CLASSES = {
    # 基础分页
    'standard': StandardPagination,
    'small': SmallPagination,
    'large': LargePagination,
    'mobile': MobilePagination,

    # 游标分页
    'posts': PostCursorPagination,
    'hot_posts': HotPostCursorPagination,
    'comments': CommentCursorPagination,
    'notifications': NotificationCursorPagination,
    'infinite': InfiniteScrollPagination,

    # 特殊分页
    'search': SearchPagination,
    'feed': FeedPagination,
    'trending': TrendingPagination,
    'user_content': UserContentPagination,

    # 管理后台
    'admin': AdminPagination,
    'review_queue': ReviewQueuePagination,
}


# ===== 工具函数 =====
def get_pagination_class(pagination_type='standard'):
    """
    根据分页类型获取对应的分页类

    Args:
        pagination_type (str): 分页类型

    Returns:
        class: 分页类
    """
    return PAGINATION_CLASSES.get(pagination_type, StandardPagination)


def paginate_queryset(queryset, request, pagination_type='standard', **kwargs):
    """
    对查询集进行分页

    Args:
        queryset: Django查询集
        request: HTTP请求对象
        pagination_type: 分页类型
        **kwargs: 传递给分页器的额外参数

    Returns:
        tuple: (分页后的数据, 分页器实例)
    """
    pagination_class = get_pagination_class(pagination_type)
    paginator = pagination_class()

    # 设置请求对象，用于分页器内部使用
    paginator.request = request

    # 应用额外参数
    for key, value in kwargs.items():
        if hasattr(paginator, key):
            setattr(paginator, key, value)

    paginated_queryset = paginator.paginate_queryset(queryset, request)

    return paginated_queryset, paginator


def create_paginated_response(data, paginator):
    """
    创建分页响应

    Args:
        data: 序列化后的数据
        paginator: 分页器实例

    Returns:
        Response: DRF响应对象
    """
    if paginator is not None:
        return paginator.get_paginated_response(data)

    # 如果没有分页器，返回标准格式
    return Response(OrderedDict([
        ('success', True),
        ('code', 200),
        ('message', 'success'),
        ('data', OrderedDict([
            ('count', len(data) if isinstance(data, (list, tuple)) else 1),
            ('items', data)
        ]))
    ]))


# ===== 分页装饰器 =====
def paginated_response(pagination_type='standard', **pagination_kwargs):
    """
    分页装饰器 - 简化视图中的分页处理

    Args:
        pagination_type (str): 分页类型
        **pagination_kwargs: 分页器参数

    Returns:
        function: 装饰器函数
    """

    def decorator(view_func):
        def wrapper(self, request, *args, **kwargs):
            # 获取查询集
            queryset = view_func(self, request, *args, **kwargs)

            # 如果返回的不是查询集，直接返回
            if not hasattr(queryset, 'model'):
                return queryset

            # 进行分页
            paginated_data, paginator = paginate_queryset(
                queryset, request, pagination_type, **pagination_kwargs
            )

            # 序列化数据
            serializer_class = getattr(self, 'serializer_class', None)
            if serializer_class:
                serializer = serializer_class(
                    paginated_data,
                    many=True,
                    context={'request': request}
                )
                return create_paginated_response(serializer.data, paginator)

            return create_paginated_response(list(paginated_data), paginator)

        return wrapper

    return decorator