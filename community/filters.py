# -*- coding: utf-8 -*-
# @Time    : 2025/8/23 15:35
# @Author  : Delock

from django_filters import rest_framework as filters
from django.db.models import Q, Count
from django.utils import timezone
from datetime import timedelta, datetime
from django.contrib.auth.models import User

from .models import (
    Post, PostCategory, Comment, Topic, UserAction,
    Report, Notification, PostCollection, UserFollow,
    BlockedUser
)


# ===== 基础过滤器类 =====
class BaseFilter(filters.FilterSet):
    """基础过滤器类，提供通用功能"""

    # 时间范围过滤
    created_after = filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')

    # 日期范围过滤
    date_range = filters.CharFilter(method='filter_date_range')

    def filter_date_range(self, queryset, name, value):
        """日期范围过滤方法"""
        now = timezone.now()

        if value == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return queryset.filter(created_at__gte=start_date)
        elif value == 'yesterday':
            yesterday = now - timedelta(days=1)
            start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1)
            return queryset.filter(created_at__gte=start_date, created_at__lt=end_date)
        elif value == 'week':
            start_date = now - timedelta(days=7)
            return queryset.filter(created_at__gte=start_date)
        elif value == 'month':
            start_date = now - timedelta(days=30)
            return queryset.filter(created_at__gte=start_date)
        elif value == 'quarter':
            start_date = now - timedelta(days=90)
            return queryset.filter(created_at__gte=start_date)
        elif value == 'year':
            start_date = now - timedelta(days=365)
            return queryset.filter(created_at__gte=start_date)

        return queryset


# ===== 帖子过滤器 =====
class PostFilter(BaseFilter):
    """帖子过滤器"""

    # 基础字段过滤
    author = filters.ModelChoiceFilter(queryset=User.objects.all())
    author_username = filters.CharFilter(field_name='author__username', lookup_expr='icontains')
    category = filters.ModelChoiceFilter(queryset=PostCategory.objects.filter(is_active=True))
    category_slug = filters.CharFilter(field_name='category__slug')
    post_type = filters.ChoiceFilter(choices=Post.POST_TYPE_CHOICES)
    status = filters.MultipleChoiceFilter(choices=Post.STATUS_CHOICES)

    # 文本搜索
    search = filters.CharFilter(method='filter_search')
    title = filters.CharFilter(field_name='title', lookup_expr='icontains')
    content = filters.CharFilter(field_name='content', lookup_expr='icontains')

    # 布尔字段
    is_featured = filters.BooleanFilter()
    is_top = filters.BooleanFilter()
    is_published = filters.BooleanFilter(method='filter_is_published')

    # 位置过滤
    location = filters.CharFilter(field_name='location', lookup_expr='icontains')
    has_location = filters.BooleanFilter(method='filter_has_location')
    nearby = filters.CharFilter(method='filter_nearby')

    # 数值范围过滤
    view_count_min = filters.NumberFilter(field_name='view_count', lookup_expr='gte')
    view_count_max = filters.NumberFilter(field_name='view_count', lookup_expr='lte')
    like_count_min = filters.NumberFilter(field_name='like_count', lookup_expr='gte')
    like_count_max = filters.NumberFilter(field_name='like_count', lookup_expr='lte')
    comment_count_min = filters.NumberFilter(field_name='comment_count', lookup_expr='gte')
    comment_count_max = filters.NumberFilter(field_name='comment_count', lookup_expr='lte')

    # 热度分数过滤
    hot_score_min = filters.NumberFilter(field_name='hot_score', lookup_expr='gte')
    hot_score_max = filters.NumberFilter(field_name='hot_score', lookup_expr='lte')
    quality_score_min = filters.NumberFilter(field_name='quality_score', lookup_expr='gte')

    # 时间过滤
    published_after = filters.DateTimeFilter(field_name='published_at', lookup_expr='gte')
    published_before = filters.DateTimeFilter(field_name='published_at', lookup_expr='lte')

    # 特殊过滤
    trending = filters.BooleanFilter(method='filter_trending')
    popular = filters.BooleanFilter(method='filter_popular')
    recent = filters.BooleanFilter(method='filter_recent')
    has_media = filters.BooleanFilter(method='filter_has_media')
    media_type = filters.ChoiceFilter(method='filter_media_type', choices=[
        ('image', '图片'),
        ('video', '视频'),
    ])

    # 用户相关过滤
    liked_by_user = filters.BooleanFilter(method='filter_liked_by_user')
    collected_by_user = filters.BooleanFilter(method='filter_collected_by_user')
    following_authors = filters.BooleanFilter(method='filter_following_authors')

    # 排序
    ordering = filters.OrderingFilter(
        fields=(
            ('created_at', 'created_at'),
            ('published_at', 'published_at'),
            ('updated_at', 'updated_at'),
            ('view_count', 'view_count'),
            ('like_count', 'like_count'),
            ('comment_count', 'comment_count'),
            ('hot_score', 'hot_score'),
            ('quality_score', 'quality_score'),
        ),
        field_labels={
            'created_at': '创建时间',
            'published_at': '发布时间',
            'updated_at': '更新时间',
            'view_count': '浏览量',
            'like_count': '点赞数',
            'comment_count': '评论数',
            'hot_score': '热度分数',
            'quality_score': '质量分数',
        }
    )

    class Meta:
        model = Post
        fields = []

    def filter_search(self, queryset, name, value):
        """全文搜索"""
        if not value:
            return queryset

        return queryset.filter(
            Q(title__icontains=value) |
            Q(content__icontains=value) |
            Q(author__username__icontains=value) |
            Q(location__icontains=value)
        )

    def filter_is_published(self, queryset, name, value):
        """发布状态过滤"""
        if value:
            return queryset.filter(status='approved', published_at__isnull=False)
        else:
            return queryset.exclude(status='approved')

    def filter_has_location(self, queryset, name, value):
        """位置信息过滤"""
        if value:
            return queryset.exclude(Q(location='') | Q(location__isnull=True))
        else:
            return queryset.filter(Q(location='') | Q(location__isnull=True))

    def filter_nearby(self, queryset, name, value):
        """附近帖子过滤 - 需要传入 lat,lng,radius 格式"""
        try:
            lat, lng, radius = value.split(',')
            lat, lng, radius = float(lat), float(lng), float(radius)

            # 这里可以实现地理位置计算
            # 简化版本：根据经纬度范围过滤
            lat_range = radius / 111.0  # 大约每度111km
            lng_range = radius / (111.0 * abs(lat))

            return queryset.filter(
                latitude__range=(lat - lat_range, lat + lat_range),
                longitude__range=(lng - lng_range, lng + lng_range)
            ).exclude(latitude__isnull=True, longitude__isnull=True)
        except (ValueError, TypeError):
            return queryset

    def filter_trending(self, queryset, name, value):
        """热门趋势过滤"""
        if value:
            # 最近24小时内的高热度帖子
            yesterday = timezone.now() - timedelta(hours=24)
            return queryset.filter(
                published_at__gte=yesterday,
                hot_score__gte=50
            ).order_by('-hot_score')
        return queryset

    def filter_popular(self, queryset, name, value):
        """热门帖子过滤"""
        if value:
            return queryset.filter(
                Q(like_count__gte=50) |
                Q(comment_count__gte=20) |
                Q(view_count__gte=1000)
            ).order_by('-hot_score')
        return queryset

    def filter_recent(self, queryset, name, value):
        """最新帖子过滤"""
        if value:
            recent_time = timezone.now() - timedelta(hours=6)
            return queryset.filter(published_at__gte=recent_time)
        return queryset

    def filter_has_media(self, queryset, name, value):
        """包含媒体文件过滤"""
        if value:
            return queryset.filter(medias__isnull=False).distinct()
        else:
            return queryset.filter(medias__isnull=True)

    def filter_media_type(self, queryset, name, value):
        """媒体类型过滤"""
        return queryset.filter(medias__media_type=value).distinct()

    def filter_liked_by_user(self, queryset, name, value):
        """用户点赞的帖子"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            liked_posts = UserAction.objects.filter(
                user=self.request.user,
                action_type='like_post'
            ).values_list('post', flat=True)
            return queryset.filter(id__in=liked_posts)
        return queryset

    def filter_collected_by_user(self, queryset, name, value):
        """用户收藏的帖子"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            collected_posts = PostCollection.objects.filter(
                user=self.request.user
            ).values_list('post', flat=True)
            return queryset.filter(id__in=collected_posts)
        return queryset

    def filter_following_authors(self, queryset, name, value):
        """关注用户的帖子"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            following_users = UserFollow.objects.filter(
                follower=self.request.user
            ).values_list('following', flat=True)
            return queryset.filter(author__in=following_users)
        return queryset


# ===== 评论过滤器 =====
class CommentFilter(BaseFilter):
    """评论过滤器"""

    # 基础字段过滤
    author = filters.ModelChoiceFilter(queryset=User.objects.all())
    author_username = filters.CharFilter(field_name='author__username', lookup_expr='icontains')
    post = filters.ModelChoiceFilter(queryset=Post.objects.all())
    parent = filters.ModelChoiceFilter(queryset=Comment.objects.all())

    # 文本搜索
    search = filters.CharFilter(method='filter_search')
    content = filters.CharFilter(field_name='content', lookup_expr='icontains')

    # 布尔字段
    is_author_reply = filters.BooleanFilter()
    is_featured = filters.BooleanFilter()
    is_deleted = filters.BooleanFilter()
    is_top_level = filters.BooleanFilter(method='filter_is_top_level')

    # 数值范围过滤
    like_count_min = filters.NumberFilter(field_name='like_count', lookup_expr='gte')
    like_count_max = filters.NumberFilter(field_name='like_count', lookup_expr='lte')
    reply_count_min = filters.NumberFilter(field_name='reply_count', lookup_expr='gte')
    reply_count_max = filters.NumberFilter(field_name='reply_count', lookup_expr='lte')

    # 位置过滤
    location = filters.CharFilter(field_name='location', lookup_expr='icontains')

    # 用户相关过滤
    liked_by_user = filters.BooleanFilter(method='filter_liked_by_user')

    # 排序
    ordering = filters.OrderingFilter(
        fields=(
            ('created_at', 'created_at'),
            ('like_count', 'like_count'),
            ('reply_count', 'reply_count'),
        ),
        field_labels={
            'created_at': '创建时间',
            'like_count': '点赞数',
            'reply_count': '回复数',
        }
    )

    class Meta:
        model = Comment
        fields = []

    def filter_search(self, queryset, name, value):
        """评论搜索"""
        if not value:
            return queryset

        return queryset.filter(
            Q(content__icontains=value) |
            Q(author__username__icontains=value)
        )

    def filter_is_top_level(self, queryset, name, value):
        """顶级评论过滤"""
        if value:
            return queryset.filter(parent__isnull=True)
        else:
            return queryset.filter(parent__isnull=False)

    def filter_liked_by_user(self, queryset, name, value):
        """用户点赞的评论"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            liked_comments = UserAction.objects.filter(
                user=self.request.user,
                action_type='like_comment'
            ).values_list('comment', flat=True)
            return queryset.filter(id__in=liked_comments)
        return queryset


# ===== 用户过滤器 =====
class UserFilter(BaseFilter):
    """用户过滤器"""

    # 基础字段过滤
    username = filters.CharFilter(field_name='username', lookup_expr='icontains')
    email = filters.CharFilter(field_name='email', lookup_expr='icontains')
    first_name = filters.CharFilter(field_name='first_name', lookup_expr='icontains')
    last_name = filters.CharFilter(field_name='last_name', lookup_expr='icontains')

    # 文本搜索
    search = filters.CharFilter(method='filter_search')

    # 布尔字段
    is_active = filters.BooleanFilter()
    is_staff = filters.BooleanFilter()
    is_superuser = filters.BooleanFilter()

    # 时间过滤
    joined_after = filters.DateTimeFilter(field_name='date_joined', lookup_expr='gte')
    joined_before = filters.DateTimeFilter(field_name='date_joined', lookup_expr='lte')
    last_login_after = filters.DateTimeFilter(field_name='last_login', lookup_expr='gte')
    last_login_before = filters.DateTimeFilter(field_name='last_login', lookup_expr='lte')

    # 统计过滤
    min_posts = filters.NumberFilter(method='filter_min_posts')
    min_followers = filters.NumberFilter(method='filter_min_followers')
    min_following = filters.NumberFilter(method='filter_min_following')

    # 用户关系过滤
    is_followed = filters.BooleanFilter(method='filter_is_followed')
    is_following = filters.BooleanFilter(method='filter_is_following')
    is_blocked = filters.BooleanFilter(method='filter_is_blocked')
    mutual_follow = filters.BooleanFilter(method='filter_mutual_follow')

    # 排序
    ordering = filters.OrderingFilter(
        fields=(
            ('date_joined', 'date_joined'),
            ('last_login', 'last_login'),
            ('username', 'username'),
        ),
        field_labels={
            'date_joined': '注册时间',
            'last_login': '最后登录',
            'username': '用户名',
        }
    )

    class Meta:
        model = User
        fields = []

    def filter_search(self, queryset, name, value):
        """用户搜索"""
        if not value:
            return queryset

        return queryset.filter(
            Q(username__icontains=value) |
            Q(first_name__icontains=value) |
            Q(last_name__icontains=value) |
            Q(email__icontains=value)
        )

    def filter_min_posts(self, queryset, name, value):
        """最少帖子数过滤"""
        return queryset.annotate(
            posts_count=Count('posts', filter=Q(posts__status='approved'))
        ).filter(posts_count__gte=value)

    def filter_min_followers(self, queryset, name, value):
        """最少粉丝数过滤"""
        return queryset.annotate(
            followers_count=Count('followers')
        ).filter(followers_count__gte=value)

    def filter_min_following(self, queryset, name, value):
        """最少关注数过滤"""
        return queryset.annotate(
            following_count=Count('following')
        ).filter(following_count__gte=value)

    def filter_is_followed(self, queryset, name, value):
        """当前用户关注的用户"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            followed_users = UserFollow.objects.filter(
                follower=self.request.user
            ).values_list('following', flat=True)
            return queryset.filter(id__in=followed_users)
        return queryset

    def filter_is_following(self, queryset, name, value):
        """关注当前用户的用户"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            followers = UserFollow.objects.filter(
                following=self.request.user
            ).values_list('follower', flat=True)
            return queryset.filter(id__in=followers)
        return queryset

    def filter_is_blocked(self, queryset, name, value):
        """被当前用户拉黑的用户"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            blocked_users = BlockedUser.objects.filter(
                user=self.request.user
            ).values_list('blocked_user', flat=True)
            return queryset.filter(id__in=blocked_users)
        return queryset

    def filter_mutual_follow(self, queryset, name, value):
        """互相关注的用户"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            mutual_follows = UserFollow.objects.filter(
                follower=self.request.user,
                is_mutual=True
            ).values_list('following', flat=True)
            return queryset.filter(id__in=mutual_follows)
        return queryset


# ===== 话题过滤器 =====
class TopicFilter(BaseFilter):
    """话题过滤器"""

    # 基础字段过滤
    name = filters.CharFilter(field_name='name', lookup_expr='icontains')
    slug = filters.CharFilter(field_name='slug')
    creator = filters.ModelChoiceFilter(queryset=User.objects.all())
    creator_username = filters.CharFilter(field_name='creator__username', lookup_expr='icontains')
    status = filters.MultipleChoiceFilter(choices=Topic.STATUS_CHOICES)

    # 文本搜索
    search = filters.CharFilter(method='filter_search')
    description = filters.CharFilter(field_name='description', lookup_expr='icontains')

    # 布尔字段
    is_official = filters.BooleanFilter()
    is_trending = filters.BooleanFilter()
    is_featured = filters.BooleanFilter()

    # 数值范围过滤
    post_count_min = filters.NumberFilter(field_name='post_count', lookup_expr='gte')
    post_count_max = filters.NumberFilter(field_name='post_count', lookup_expr='lte')
    follow_count_min = filters.NumberFilter(field_name='follow_count', lookup_expr='gte')
    follow_count_max = filters.NumberFilter(field_name='follow_count', lookup_expr='lte')
    hot_score_min = filters.NumberFilter(field_name='hot_score', lookup_expr='gte')

    # 特殊过滤
    popular = filters.BooleanFilter(method='filter_popular')
    active = filters.BooleanFilter(method='filter_active')

    # 用户相关过滤
    followed_by_user = filters.BooleanFilter(method='filter_followed_by_user')

    # 排序
    ordering = filters.OrderingFilter(
        fields=(
            ('created_at', 'created_at'),
            ('post_count', 'post_count'),
            ('follow_count', 'follow_count'),
            ('hot_score', 'hot_score'),
            ('name', 'name'),
        ),
        field_labels={
            'created_at': '创建时间',
            'post_count': '帖子数',
            'follow_count': '关注数',
            'hot_score': '热度分数',
            'name': '话题名称',
        }
    )

    class Meta:
        model = Topic
        fields = []

    def filter_search(self, queryset, name, value):
        """话题搜索"""
        if not value:
            return queryset

        return queryset.filter(
            Q(name__icontains=value) |
            Q(description__icontains=value) |
            Q(creator__username__icontains=value)
        )

    def filter_popular(self, queryset, name, value):
        """热门话题过滤"""
        if value:
            return queryset.filter(
                Q(post_count__gte=10) |
                Q(follow_count__gte=20) |
                Q(hot_score__gte=30)
            ).order_by('-hot_score')
        return queryset

    def filter_active(self, queryset, name, value):
        """活跃话题过滤（最近有新帖子）"""
        if value:
            recent_time = timezone.now() - timedelta(days=7)
            active_topics = Post.objects.filter(
                published_at__gte=recent_time
                # 这里需要根据实际的话题-帖子关联方式调整
            ).values_list('topic', flat=True).distinct()
            return queryset.filter(id__in=active_topics)
        return queryset

    def filter_followed_by_user(self, queryset, name, value):
        """用户关注的话题"""
        if value and hasattr(self.request, 'user') and self.request.user.is_authenticated:
            followed_topics = UserAction.objects.filter(
                user=self.request.user,
                action_type='follow_topic'
            ).values_list('topic', flat=True)
            return queryset.filter(id__in=followed_topics)
        return queryset


# ===== 分类过滤器 =====
class PostCategoryFilter(BaseFilter):
    """帖子分类过滤器"""

    # 基础字段过滤
    name = filters.CharFilter(field_name='name', lookup_expr='icontains')
    slug = filters.CharFilter(field_name='slug')
    color = filters.CharFilter()

    # 文本搜索
    search = filters.CharFilter(method='filter_search')

    # 布尔字段
    is_active = filters.BooleanFilter()

    # 数值范围过滤
    post_count_min = filters.NumberFilter(field_name='post_count', lookup_expr='gte')
    post_count_max = filters.NumberFilter(field_name='post_count', lookup_expr='lte')
    sort_order = filters.NumberFilter()

    # 特殊过滤
    has_posts = filters.BooleanFilter(method='filter_has_posts')

    # 排序
    ordering = filters.OrderingFilter(
        fields=(
            ('sort_order', 'sort_order'),
            ('post_count', 'post_count'),
            ('name', 'name'),
            ('created_at', 'created_at'),
        ),
        field_labels={
            'sort_order': '排序',
            'post_count': '帖子数',
            'name': '分类名称',
            'created_at': '创建时间',
        }
    )

    class Meta:
        model = PostCategory
        fields = []

    def filter_search(self, queryset, name, value):
        """分类搜索"""
        if not value:
            return queryset

        return queryset.filter(name__icontains=value)

    def filter_has_posts(self, queryset, name, value):
        """有帖子的分类"""
        if value:
            return queryset.filter(post_count__gt=0)
        else:
            return queryset.filter(post_count=0)


# ===== 通知过滤器 =====
class NotificationFilter(BaseFilter):
    """通知过滤器"""

    # 基础字段过滤
    sender = filters.ModelChoiceFilter(queryset=User.objects.all())
    sender_username = filters.CharFilter(field_name='sender__username', lookup_expr='icontains')
    notification_type = filters.MultipleChoiceFilter(choices=Notification.NOTIFICATION_TYPE_CHOICES)

    # 文本搜索
    search = filters.CharFilter(method='filter_search')
    title = filters.CharFilter(field_name='title', lookup_expr='icontains')
    content = filters.CharFilter(field_name='content', lookup_expr='icontains')

    # 布尔字段
    is_read = filters.BooleanFilter()

    # 时间过滤
    read_after = filters.DateTimeFilter(field_name='read_at', lookup_expr='gte')
    read_before = filters.DateTimeFilter(field_name='read_at', lookup_expr='lte')

    # 排序
    ordering = filters.OrderingFilter(
        fields=(
            ('created_at', 'created_at'),
            ('read_at', 'read_at'),
        ),
        field_labels={
            'created_at': '创建时间',
            'read_at': '阅读时间',
        }
    )

    class Meta:
        model = Notification
        fields = []

    def filter_search(self, queryset, name, value):
        """通知搜索"""
        if not value:
            return queryset

        return queryset.filter(
            Q(title__icontains=value) |
            Q(content__icontains=value) |
            Q(sender__username__icontains=value)
        )


# ===== 举报过滤器 =====
class ReportFilter(BaseFilter):
    """举报过滤器"""

    # 基础字段过滤
    reporter = filters.ModelChoiceFilter(queryset=User.objects.all())
    reporter_username = filters.CharFilter(field_name='reporter__username', lookup_expr='icontains')
    handler = filters.ModelChoiceFilter(queryset=User.objects.all())
    content_type = filters.MultipleChoiceFilter(choices=Report.CONTENT_TYPE_CHOICES)
    report_type = filters.MultipleChoiceFilter(choices=Report.REPORT_TYPE_CHOICES)
    status = filters.MultipleChoiceFilter(choices=Report.STATUS_CHOICES)

    # 文本搜索
    search = filters.CharFilter(method='filter_search')
    reason = filters.CharFilter(field_name='reason', lookup_expr='icontains')

    # 时间过滤
    handled_after = filters.DateTimeFilter(field_name='handled_at', lookup_expr='gte')
    handled_before = filters.DateTimeFilter(field_name='handled_at', lookup_expr='lte')

    # 特殊过滤
    pending = filters.BooleanFilter(method='filter_pending')
    urgent = filters.BooleanFilter(method='filter_urgent')

    # 排序
    ordering = filters.OrderingFilter(
        fields=(
            ('created_at', 'created_at'),
            ('handled_at', 'handled_at'),
        ),
        field_labels={
            'created_at': '创建时间',
            'handled_at': '处理时间',
        }
    )

    class Meta:
        model = Report
        fields = []

    def filter_search(self, queryset, name, value):
        """举报搜索"""
        if not value:
            return queryset

        return queryset.filter(
            Q(reason__icontains=value) |
            Q(reporter__username__icontains=value) |
            Q(handle_note__icontains=value)
        )

    def filter_pending(self, queryset, name, value):
        """待处理举报"""
        if value:
            return queryset.filter(status='pending')
        return queryset

    def filter_urgent(self, queryset, name, value):
        """紧急举报（某些类型的举报优先级更高）"""
        if value:
            urgent_types = ['porn', 'violence', 'fraud', 'abuse']
            return queryset.filter(report_type__in=urgent_types, status='pending')
        return queryset


# ===== 管理后台过滤器 =====
class AdminPostFilter(PostFilter):
    """管理后台帖子过滤器"""
    author = filters.ModelChoiceFilter(queryset=User.objects.all())
    author_username = filters.CharFilter(field_name='author__username', lookup_expr='icontains')
    category = filters.ModelChoiceFilter(queryset=PostCategory.objects.filter(is_active=True))
    category_slug = filters.CharFilter(field_name='category__slug')  # 添加这行

    # 审核相关过滤
    reviewer = filters.ModelChoiceFilter(queryset=User.objects.filter(is_staff=True))
    review_priority = filters.NumberFilter()
    review_priority_min = filters.NumberFilter(field_name='review_priority', lookup_expr='gte')
    auto_review_score_min = filters.NumberFilter(field_name='auto_review_score', lookup_expr='gte')
    auto_review_score_max = filters.NumberFilter(field_name='auto_review_score', lookup_expr='lte')

    # 违规相关
    violation_type = filters.CharFilter(field_name='violation_type', lookup_expr='icontains')
    violation_count_min = filters.NumberFilter(field_name='violation_count', lookup_expr='gte')
    report_count_min = filters.NumberFilter(field_name='report_count', lookup_expr='gte')

    # 时间过滤
    reviewed_after = filters.DateTimeFilter(field_name='reviewed_at', lookup_expr='gte')
    reviewed_before = filters.DateTimeFilter(field_name='reviewed_at', lookup_expr='lte')

    # 特殊过滤
    needs_review = filters.BooleanFilter(method='filter_needs_review')
    auto_review_failed = filters.BooleanFilter(method='filter_auto_review_failed')
    high_priority = filters.BooleanFilter(method='filter_high_priority')

    def filter_needs_review(self, queryset, name, value):
        """需要人工审核的帖子"""
        if value:
            return queryset.filter(status__in=['pending', 'reviewing'])
        return queryset

    def filter_auto_review_failed(self, queryset, name, value):
        """自动审核失败的帖子"""
        if value:
            return queryset.filter(
                status='pending',
                auto_review_score__lt=60
            )
        return queryset

    def filter_high_priority(self, queryset, name, value):
        """高优先级审核的帖子"""
        if value:
            return queryset.filter(review_priority__gte=8)
        return queryset

    class Meta:
        model = Post
        fields = ['category_slug']  # 添加到fields中


# ===== 过滤器工具函数 =====
def get_filter_class(model_name):
    """根据模型名称获取对应的过滤器类"""
    filter_mapping = {
        'post': PostFilter,
        'comment': CommentFilter,
        'user': UserFilter,
        'topic': TopicFilter,
        'category': PostCategoryFilter,
        'notification': NotificationFilter,
        'report': ReportFilter,
        'admin_post': AdminPostFilter,
    }
    return filter_mapping.get(model_name.lower())


def apply_filters(queryset, request, filter_class):
    """应用过滤器到查询集"""
    if filter_class:
        filterset = filter_class(request.GET, queryset=queryset, request=request)
        if filterset.is_valid():
            return filterset.qs
    return queryset


# ===== 自定义过滤器字段 =====
class MultipleCharFilter(filters.BaseInFilter, filters.CharFilter):
    """多值字符串过滤器"""
    pass


class DateRangeFilter(filters.Filter):
    """日期范围过滤器"""

    def filter(self, qs, value):
        if not value:
            return qs

        try:
            start_date, end_date = value.split(',')
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

            return qs.filter(
                **{f'{self.field_name}__date__gte': start_date,
                   f'{self.field_name}__date__lte': end_date}
            )
        except (ValueError, AttributeError):
            return qs


class NumberRangeFilter(filters.Filter):
    """数值范围过滤器"""

    def filter(self, qs, value):
        if not value:
            return qs

        try:
            min_val, max_val = value.split(',')
            min_val = float(min_val) if min_val else None
            max_val = float(max_val) if max_val else None

            if min_val is not None:
                qs = qs.filter(**{f'{self.field_name}__gte': min_val})
            if max_val is not None:
                qs = qs.filter(**{f'{self.field_name}__lte': max_val})

            return qs
        except (ValueError, AttributeError):
            return qs