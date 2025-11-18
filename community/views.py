# -*- coding: utf-8 -*-
# @Time    : 2025/8/23 15:35
# @Author  : Delock

from django.db import transaction
from django.db.models import F, Q, Count, Sum
from django.utils import timezone

from datetime import timedelta

from rest_framework import status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet, ViewSet
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly

from community.models import (
    Post, PostCategory, Comment, Topic, UserAction,
    Report, Notification, UserFollow, PostCollection, BlockedUser,
    PostView, ReviewLog
)
from community.serializers import (
    PostListSerializer, PostDetailSerializer, CreatePostSerializer, UpdatePostSerializer,
    CommentSerializer, CreateCommentSerializer, UserDetailSerializer, BasicUserSerializer,
    PostCategorySerializer, TopicSerializer, SimpleTopicSerializer, UserActionSerializer,
    ReportSerializer, NotificationSerializer,
    PostCollectionSerializer, UserFollowSerializer,
)
from community.filters import (
    PostFilter, CommentFilter, UserFilter, TopicFilter, PostCategoryFilter,
    NotificationFilter, ReportFilter, AdminPostFilter, apply_filters
)
from community.pagination import (
    paginate_queryset, create_paginated_response
)
from user.models import User
from utils.authentication import UserAuthentication, AdminAuthentication
from utils.permission import IsUserOwner


# ===== 基础视图类 =====
class BaseViewSet(ModelViewSet):
    """基础视图集，提供通用功能"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUserOwner]

    def get_permissions(self):
        """根据动作动态设置权限"""
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsUserOwner]
        return [permission() for permission in permission_classes]

    def perform_create(self, serializer):
        """创建时设置用户"""
        if hasattr(serializer.Meta.model, 'author'):
            serializer.save(author=self.request.user)
        elif hasattr(serializer.Meta.model, 'user'):
            serializer.save(user=self.request.user)
        else:
            serializer.save()

    def get_queryset(self):
        """获取查询集并应用过滤"""
        queryset = super().get_queryset()

        # 应用过滤器
        filter_class = getattr(self, 'filterset_class', None)
        if filter_class:
            queryset = apply_filters(queryset, self.request, filter_class)

        # 排除已删除和被拉黑用户的内容
        if self.request.user.is_authenticated:
            blocked_users = BlockedUser.objects.filter(
                user=self.request.user
            ).values_list('blocked_user', flat=True)

            if hasattr(queryset.model, 'author'):
                queryset = queryset.exclude(author__in=blocked_users)
            elif hasattr(queryset.model, 'user'):
                queryset = queryset.exclude(user__in=blocked_users)

        return queryset

    def list(self, request, *args, **kwargs):
        """列表视图with分页"""
        queryset = self.filter_queryset(self.get_queryset())

        # 获取分页类型
        pagination_type = request.GET.get('pagination_type', 'standard')
        paginated_queryset, paginator = paginate_queryset(
            queryset, request, pagination_type
        )

        serializer = self.get_serializer(paginated_queryset, many=True)
        return create_paginated_response(serializer.data, paginator)


# ===== 用户相关视图 =====
class UserViewSet(ReadOnlyModelViewSet):
    """用户视图集 - 支持通过 id 或 username 查询"""
    queryset = User.objects.filter(is_active=True)
    serializer_class = UserDetailSerializer
    filterset_class = UserFilter
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUserOwner]
    lookup_field = 'username'  # 默认使用 username

    def get_object(self):
        """
        支持通过 id 或 username 查询用户
        - URL中的值如果是纯数字，则按ID查询
        - 否则按username查询

        示例:
        - /users/123/  -> 按ID查询
        - /users/john_doe/  -> 按username查询
        """
        lookup_value = self.kwargs.get(self.lookup_field)

        try:
            # 判断是数字ID还是username
            if lookup_value.isdigit():
                # 如果是纯数字，按ID查询
                user = User.objects.filter(is_active=True).get(id=int(lookup_value))
            else:
                # 否则按username查询
                user = User.objects.filter(is_active=True).get(username=lookup_value)

            # 检查权限
            self.check_object_permissions(self.request, user)
            return user

        except User.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('用户不存在')

    def get_serializer_class(self):
        if self.action == 'list':
            return BasicUserSerializer
        return UserDetailSerializer

    @action(detail=True, methods=['get'])
    def posts(self, request, username=None):
        """
        获取用户的帖子
        支持通过 id 或 username 访问

        URL示例:
        - /users/123/posts/  -> 通过ID
        - /users/john_doe/posts/  -> 通过username
        """
        user = self.get_object()
        posts = Post.objects.filter(
            author=user,
            status='approved'
        ).order_by('-published_at')

        paginated_posts, paginator = paginate_queryset(
            posts, request, 'user_content'
        )

        serializer = PostListSerializer(
            paginated_posts, many=True, context={'request': request}
        )
        return create_paginated_response(serializer.data, paginator)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated])
    def collections(self, request, username=None):
        """获取用户的收藏"""
        user = self.get_object()
        if user != request.user:
            return Response({'detail': '无权访问'}, status=status.HTTP_403_FORBIDDEN)

        collections = PostCollection.objects.filter(
            user=user
        ).select_related('post__author', 'post__category')

        paginated_collections, paginator = paginate_queryset(
            collections, request, 'standard'
        )

        serializer = PostCollectionSerializer(
            paginated_collections, many=True, context={'request': request}
        )
        return create_paginated_response(serializer.data, paginator)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def follow(self, request, username=None):
        """关注/取消关注用户"""
        target_user = self.get_object()

        if target_user == request.user:
            return Response({'detail': '不能关注自己'}, status=status.HTTP_400_BAD_REQUEST)

        follow_relation, created = UserFollow.objects.get_or_create(
            follower=request.user,
            following=target_user
        )

        if not created:
            follow_relation.delete()
            # 记录取消关注行为
            UserAction.objects.create(
                user=request.user,
                action_type='unfollow_user',
                target_user=target_user
            )
            return Response({'detail': '已取消关注', 'followed': False})
        else:
            # 记录关注行为
            UserAction.objects.create(
                user=request.user,
                action_type='follow_user',
                target_user=target_user
            )
            return Response({'detail': '关注成功', 'followed': True})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def block(self, request, username=None):
        """拉黑/取消拉黑用户"""
        target_user = self.get_object()

        if target_user == request.user:
            return Response({'detail': '不能拉黑自己'}, status=status.HTTP_400_BAD_REQUEST)

        blocked_relation, created = BlockedUser.objects.get_or_create(
            user=request.user,
            blocked_user=target_user,
            defaults={'reason': request.data.get('reason', '')}
        )

        if not created:
            blocked_relation.delete()
            return Response({'detail': '已取消拉黑', 'blocked': False})
        else:
            # 如果存在关注关系，先取消关注
            UserFollow.objects.filter(
                Q(follower=request.user, following=target_user) |
                Q(follower=target_user, following=request.user)
            ).delete()

            return Response({'detail': '拉黑成功', 'blocked': True})

    # ===== 用户统计信息 =====
    @action(detail=True, methods=['get'])
    def stats(self, request, username=None):
        """
        获取用户统计信息（粉丝数、关注数、获赞量等）
        支持通过 id 或 username 访问
        """
        user = self.get_object()

        # 粉丝数
        followers_count = UserFollow.objects.filter(following=user).count()

        # 关注数
        following_count = UserFollow.objects.filter(follower=user).count()

        # 获赞总量（帖子点赞 + 评论点赞）
        post_likes = Post.objects.filter(
            author=user,
            status='approved'
        ).aggregate(total_likes=Sum('like_count'))['total_likes'] or 0

        comment_likes = Comment.objects.filter(
            author=user,
            is_deleted=False
        ).aggregate(total_likes=Sum('like_count'))['total_likes'] or 0

        total_likes = post_likes + comment_likes

        # 帖子总数
        posts_count = Post.objects.filter(
            author=user,
            status='approved'
        ).count()

        # 评论总数
        comments_count = Comment.objects.filter(
            author=user,
            is_deleted=False
        ).count()

        # 收藏总数
        collections_count = PostCollection.objects.filter(user=user).count()

        # 浏览总量
        total_views = Post.objects.filter(
            author=user,
            status='approved'
        ).aggregate(total_views=Sum('view_count'))['total_views'] or 0

        return Response({
            'success': True,
            'data': {
                'user_id': user.id,
                'username': user.username,
                'followers_count': followers_count,
                'following_count': following_count,
                'total_likes': total_likes,
                'posts_count': posts_count,
                'comments_count': comments_count,
                'collections_count': collections_count,
                'total_views': total_views,
            }
        })

    # ===== 关注列表 =====
    @action(detail=True, methods=['get'])
    def following_list(self, request, username=None):
        """
        获取用户的关注列表
        支持通过 id 或 username 访问
        """
        user = self.get_object()

        # 获取关注关系
        following_relations = UserFollow.objects.filter(
            follower=user
        ).select_related('following').order_by('-created_at')

        # 分页
        paginated_relations, paginator = paginate_queryset(
            following_relations, request, 'standard'
        )

        serializer = UserFollowSerializer(
            paginated_relations,
            many=True,
            context={'request': request, 'type': 'following'}
        )

        return create_paginated_response(serializer.data, paginator)

    # ===== 粉丝列表 =====
    @action(detail=True, methods=['get'])
    def followers_list(self, request, username=None):
        """
        获取用户的粉丝列表
        支持通过 id 或 username 访问
        """
        user = self.get_object()

        # 获取粉丝关系
        follower_relations = UserFollow.objects.filter(
            following=user
        ).select_related('follower').order_by('-created_at')

        # 分页
        paginated_relations, paginator = paginate_queryset(
            follower_relations, request, 'standard'
        )

        serializer = UserFollowSerializer(
            paginated_relations,
            many=True,
            context={'request': request, 'type': 'followers'}
        )

        return create_paginated_response(serializer.data, paginator)

    # ===== 新增：用户完整信息接口（用于详情页） =====
    @action(detail=True, methods=['get'])
    def profile(self, request, username=None):
        """
        获取用户完整资料（用于详情页展示）
        包含：用户基本信息 + 统计数据 + 最新帖子

        URL示例:
        - /users/123/profile/  -> 通过ID
        - /users/john_doe/profile/  -> 通过username
        """
        user = self.get_object()

        # 用户基本信息
        user_data = UserDetailSerializer(user, context={'request': request}).data

        # 统计数据
        stats = {
            'followers_count': UserFollow.objects.filter(following=user).count(),
            'following_count': UserFollow.objects.filter(follower=user).count(),
            'posts_count': Post.objects.filter(author=user, status='approved').count(),
            'total_likes': (
                                   Post.objects.filter(author=user, status='approved')
                                   .aggregate(total=Sum('like_count'))['total'] or 0
                           ) + (
                                   Comment.objects.filter(author=user, is_deleted=False)
                                   .aggregate(total=Sum('like_count'))['total'] or 0
                           ),
        }

        # 最新帖子（前10条）
        recent_posts = Post.objects.filter(
            author=user,
            status='approved'
        ).select_related('category').prefetch_related('medias').order_by('-published_at')[:10]

        posts_data = PostListSerializer(
            recent_posts,
            many=True,
            context={'request': request}
        ).data

        return Response({
            'success': True,
            'data': {
                'user': user_data,
                'stats': stats,
                'recent_posts': posts_data
            }
        })


# ===== 帖子分类视图 =====
class PostCategoryViewSet(ReadOnlyModelViewSet):
    """帖子分类视图集"""
    queryset = PostCategory.objects.filter(is_active=True).order_by('sort_order')
    serializer_class = PostCategorySerializer
    filterset_class = PostCategoryFilter
    authentication_classes = [UserAuthentication]
    permission_classes = [permissions.AllowAny]

    @action(detail=True, methods=['get'])
    def posts(self, request, pk=None):
        """获取分类下的帖子"""
        category = self.get_object()
        posts = Post.objects.filter(
            category=category,
            status='approved'
        ).select_related('author', 'category').order_by('-hot_score')

        # 应用过滤
        posts = apply_filters(posts, request, PostFilter)

        paginated_posts, paginator = paginate_queryset(
            posts, request, 'standard'
        )

        serializer = PostListSerializer(
            paginated_posts, many=True, context={'request': request}
        )
        return create_paginated_response(serializer.data, paginator)


# ===== 话题视图 =====
class TopicViewSet(ReadOnlyModelViewSet):
    """话题视图集"""
    queryset = Topic.objects.filter(status='approved')
    serializer_class = TopicSerializer
    filterset_class = TopicFilter
    authentication_classes = [UserAuthentication]
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    def get_serializer_class(self):
        if self.action == 'list':
            return SimpleTopicSerializer
        return TopicSerializer

    @action(detail=True, methods=['get'])
    def posts(self, request, slug=None):
        """获取话题下的帖子"""
        topic = self.get_object()
        posts = Post.objects.filter(
            topics=topic,
            status='approved'
        ).select_related('author', 'category').order_by('-published_at')

        # 应用过滤
        posts = apply_filters(posts, request, PostFilter)

        paginated_posts, paginator = paginate_queryset(
            posts, request, 'standard'
        )

        serializer = PostListSerializer(
            paginated_posts, many=True, context={'request': request}
        )
        return create_paginated_response(serializer.data, paginator)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def follow(self, request, slug=None):
        """关注/取消关注话题"""
        topic = self.get_object()

        # 检查是否已关注
        action_exists = UserAction.objects.filter(
            user=request.user,
            action_type='follow_topic',
            topic=topic
        ).exists()

        if action_exists:
            # 取消关注
            UserAction.objects.filter(
                user=request.user,
                action_type='follow_topic',
                topic=topic
            ).delete()
            return Response({'detail': '已取消关注', 'followed': False})
        else:
            # 关注话题
            UserAction.objects.create(
                user=request.user,
                action_type='follow_topic',
                topic=topic
            )
            return Response({'detail': '关注成功', 'followed': True})


# ===== 帖子视图 =====
class PostViewSet(BaseViewSet):
    """帖子视图集"""
    queryset = Post.objects.select_related('author', 'category').prefetch_related('medias')
    filterset_class = PostFilter

    def get_serializer_class(self):
        if self.action == 'list':
            return PostListSerializer
        elif self.action in ['create']:
            return CreatePostSerializer
        elif self.action in ['update', 'partial_update']:
            return UpdatePostSerializer
        return PostDetailSerializer

    def get_queryset(self):
        """根据不同action返回不同queryset"""
        queryset = super().get_queryset()

        # 列表页只返回审核通过的帖子
        if self.action == 'list':
            queryset = queryset.filter(status='approved')

        # 详情页增加浏览记录
        if self.action == 'retrieve' and self.request.user.is_authenticated:
            post_id = self.kwargs.get('pk')
            if post_id:
                post = queryset.filter(id=post_id).first()
                if post:
                    # 记录浏览
                    post_view, created = PostView.objects.get_or_create(
                        user=self.request.user,
                        post=post
                    )
                    if not created:
                        post_view.view_count += 1
                        post_view.save()

                    # 增加帖子浏览量
                    Post.objects.filter(id=post_id).update(view_count=F('view_count') + 1)

        return queryset

    def perform_create(self, serializer):
        """创建帖子"""
        serializer.save(author=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        """点赞/取消点赞帖子"""
        post = self.get_object()

        # 检查是否已点赞
        action_exists = UserAction.objects.filter(
            user=request.user,
            action_type='like_post',
            post=post
        ).exists()

        with transaction.atomic():
            if action_exists:
                # 取消点赞
                UserAction.objects.filter(
                    user=request.user,
                    action_type='like_post',
                    post=post
                ).delete()
                Post.objects.filter(id=post.id).update(like_count=F('like_count') - 1)
                return Response({'detail': '已取消点赞', 'liked': False})
            else:
                # 点赞
                UserAction.objects.create(
                    user=request.user,
                    action_type='like_post',
                    post=post
                )
                Post.objects.filter(id=post.id).update(like_count=F('like_count') + 1)

                # 发送通知给帖子作者
                if post.author != request.user:
                    Notification.objects.create(
                        receiver=post.author,
                        sender=request.user,
                        notification_type='like_post',
                        title='收到新点赞',
                        content=f'{request.user.username} 赞了你的帖子',
                        post=post
                    )

                return Response({'detail': '点赞成功', 'liked': True})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def collect(self, request, pk=None):
        """收藏/取消收藏帖子"""
        post = self.get_object()

        collection, created = PostCollection.objects.get_or_create(
            user=request.user,
            post=post,
            defaults={
                'folder': request.data.get('folder', '默认收藏夹'),
                'note': request.data.get('note', '')
            }
        )

        with transaction.atomic():
            if not created:
                collection.delete()
                Post.objects.filter(id=post.id).update(collect_count=F('collect_count') - 1)
                return Response({'detail': '已取消收藏', 'collected': False})
            else:
                Post.objects.filter(id=post.id).update(collect_count=F('collect_count') + 1)
                return Response({'detail': '收藏成功', 'collected': True})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def share(self, request, pk=None):
        """分享帖子"""
        post = self.get_object()

        # 记录分享行为
        UserAction.objects.create(
            user=request.user,
            action_type='share_post',
            post=post
        )

        # 增加分享计数
        Post.objects.filter(id=post.id).update(share_count=F('share_count') + 1)

        return Response({'detail': '分享成功'})

    @action(detail=False, methods=['get'])
    def trending(self, request):
        """热门帖子"""
        posts = Post.objects.filter(
            status='approved'
        ).order_by('-hot_score', '-like_count')[:20]

        serializer = PostListSerializer(posts, many=True, context={'request': request})
        return Response({'posts': serializer.data})

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def feed(self, request):
        """关注动态"""
        # 获取用户关注的人
        following_users = UserFollow.objects.filter(
            follower=request.user
        ).values_list('following', flat=True)

        posts = Post.objects.filter(
            author__in=following_users,
            status='approved'
        ).select_related('author', 'category').order_by('-published_at')

        paginated_posts, paginator = paginate_queryset(
            posts, request, 'standard'
        )

        serializer = PostListSerializer(
            paginated_posts, many=True, context={'request': request}
        )
        return create_paginated_response(serializer.data, paginator)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def my_posts(self, request):
        """我的帖子"""
        posts = Post.objects.filter(
            author=request.user
        ).select_related('category').order_by('-created_at')

        paginated_posts, paginator = paginate_queryset(
            posts, request, 'standard'
        )

        serializer = PostListSerializer(
            paginated_posts, many=True, context={'request': request}
        )
        return create_paginated_response(serializer.data, paginator)


# ===== 评论视图 =====
class CommentViewSet(BaseViewSet):
    """评论视图集"""
    queryset = Comment.objects.filter(is_deleted=False).select_related('author', 'post')
    serializer_class = CommentSerializer
    filterset_class = CommentFilter

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateCommentSerializer
        return CommentSerializer

    def perform_create(self, serializer):
        """创建评论"""
        comment = serializer.save(author=self.request.user)

        # 增加帖子评论数
        Post.objects.filter(id=comment.post.id).update(
            comment_count=F('comment_count') + 1
        )

        # 发送通知
        if comment.parent:
            # 回复评论
            if comment.parent.author != self.request.user:
                Notification.objects.create(
                    receiver=comment.parent.author,
                    sender=self.request.user,
                    notification_type='reply_comment',
                    title='收到新回复',
                    content=f'{self.request.user.username} 回复了你的评论',
                    post=comment.post,
                    comment=comment
                )
        else:
            # 评论帖子
            if comment.post.author != self.request.user:
                Notification.objects.create(
                    receiver=comment.post.author,
                    sender=self.request.user,
                    notification_type='comment_post',
                    title='收到新评论',
                    content=f'{self.request.user.username} 评论了你的帖子',
                    post=comment.post,
                    comment=comment
                )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def like(self, request, pk=None):
        """点赞/取消点赞评论"""
        comment = self.get_object()

        action_exists = UserAction.objects.filter(
            user=request.user,
            action_type='like_comment',
            comment=comment
        ).exists()

        with transaction.atomic():
            if action_exists:
                UserAction.objects.filter(
                    user=request.user,
                    action_type='like_comment',
                    comment=comment
                ).delete()
                Comment.objects.filter(id=comment.id).update(like_count=F('like_count') - 1)
                return Response({'detail': '已取消点赞', 'liked': False})
            else:
                UserAction.objects.create(
                    user=request.user,
                    action_type='like_comment',
                    comment=comment
                )
                Comment.objects.filter(id=comment.id).update(like_count=F('like_count') + 1)
                return Response({'detail': '点赞成功', 'liked': True})


# ===== 用户行为视图 =====
class UserActionViewSet(ReadOnlyModelViewSet):
    """用户行为记录视图集"""
    serializer_class = UserActionSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return UserAction.objects.filter(
            user=self.request.user
        ).select_related('post', 'comment', 'topic', 'target_user').order_by('-created_at')


# ===== 通知视图 =====
class NotificationViewSet(ReadOnlyModelViewSet):
    """通知视图集"""
    serializer_class = NotificationSerializer
    filterset_class = NotificationFilter
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(
            receiver=self.request.user
        ).select_related('sender', 'post', 'comment').order_by('-created_at')

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        """标记为已读"""
        notification = self.get_object()
        notification.mark_as_read()
        return Response({'detail': '已标记为已读'})

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        """全部标记为已读"""
        Notification.objects.filter(
            receiver=request.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return Response({'detail': '全部已标记为已读'})

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """未读通知数量"""
        count = Notification.objects.filter(
            receiver=request.user,
            is_read=False
        ).count()
        return Response({'unread_count': count})


# ===== 举报视图 =====
class ReportViewSet(BaseViewSet):
    """举报视图集"""
    queryset = Report.objects.all()
    serializer_class = ReportSerializer
    filterset_class = ReportFilter

    def get_queryset(self):
        if self.request.user.is_staff:
            return Report.objects.all()
        return Report.objects.filter(reporter=self.request.user)

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)


# ===== 搜索视图 =====
class SearchView(APIView):
    """搜索功能"""
    authentication_classes = [UserAuthentication]
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        query = request.GET.get('q', '')
        search_type = request.GET.get('type', 'all')  # all, post, user, topic

        results = {}

        if search_type in ['all', 'post']:
            posts = Post.objects.filter(
                Q(title__icontains=query) | Q(content__icontains=query),
                status='approved'
            ).select_related('author', 'category')[:10]
            results['posts'] = PostListSerializer(posts, many=True, context={'request': request}).data

        if search_type in ['all', 'user']:
            users = User.objects.filter(
                Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query),
                is_active=True
            )[:10]
            results['users'] = BasicUserSerializer(users, many=True).data

        if search_type in ['all', 'topic']:
            topics = Topic.objects.filter(
                Q(name__icontains=query) | Q(description__icontains=query),
                status='approved'
            )[:10]
            results['topics'] = SimpleTopicSerializer(topics, many=True).data

        return Response(results)


# ===== 管理员审核视图 =====
class AdminPostViewSet(ModelViewSet):
    """管理员帖子审核视图"""
    queryset = Post.objects.all()
    serializer_class = PostDetailSerializer
    filterset_class = AdminPostFilter
    authentication_classes = [AdminAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # 管理员可以看到所有状态的帖子
        return Post.objects.select_related('author', 'category', 'reviewer').order_by('-created_at')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """审核通过"""
        post = self.get_object()

        with transaction.atomic():
            post.status = 'approved'
            post.reviewer = request.user
            post.reviewed_at = timezone.now()
            post.published_at = timezone.now()
            post.save()

            # 记录审核日志
            ReviewLog.objects.create(
                content_type='post',
                content_id=post.id,
                reviewer=request.user,
                action='manual_approve',
                old_status='pending',
                new_status='approved',
                note=request.data.get('note', '')
            )

            # 发送通知
            Notification.objects.create(
                receiver=post.author,
                notification_type='post_approved',
                title='帖子审核通过',
                content=f'你的帖子《{post.title}》审核通过了',
                post=post
            )

        return Response({'detail': '审核通过'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """审核拒绝"""
        post = self.get_object()
        reason = request.data.get('reason', '不符合社区规范')

        with transaction.atomic():
            post.status = 'rejected'
            post.reviewer = request.user
            post.reviewed_at = timezone.now()
            post.reject_reason = reason
            post.save()

            # 记录审核日志
            ReviewLog.objects.create(
                content_type='post',
                content_id=post.id,
                reviewer=request.user,
                action='manual_reject',
                old_status='pending',
                new_status='rejected',
                reason=reason,
                note=request.data.get('note', '')
            )

            # 发送通知
            Notification.objects.create(
                receiver=post.author,
                notification_type='post_rejected',
                title='帖子审核未通过',
                content=f'你的帖子《{post.title}》审核未通过，原因:{reason}',
                post=post
            )

        return Response({'detail': '审核拒绝'})


# ===== 宠物社区特色功能视图 =====
class PetCommunityViewSet(ViewSet):
    """宠物社区特色功能ViewSet"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]

    def list(self, request):
        """获取宠物社区首页数据"""
        # 热门宠物话题
        hot_topics = Topic.objects.filter(
            status='approved',
            name__in=['猫咪', '狗狗', '兔子', '鸟类', '其他宠物']
        ).order_by('-hot_score')[:5]

        # 今日精选帖子
        featured_posts = Post.objects.filter(
            status='approved',
            is_featured=True,
            published_at__date=timezone.now().date()
        ).select_related('author', 'category')[:3]

        # 新人推荐
        new_users = User.objects.filter(
            is_active=True,
            date_joined__gte=timezone.now() - timedelta(days=7)
        ).annotate(
            posts_count=Count('posts', filter=Q(posts__status='approved'))
        ).filter(posts_count__gte=1)[:5]

        # 宠物分类统计
        category_stats = PostCategory.objects.filter(
            is_active=True
        ).annotate(
            approved_posts=Count('posts', filter=Q(posts__status='approved'))
        ).order_by('-approved_posts')

        return Response({
            'hot_topics': SimpleTopicSerializer(hot_topics, many=True).data,
            'featured_posts': PostListSerializer(featured_posts, many=True, context={'request': request}).data,
            'new_users': BasicUserSerializer(new_users, many=True).data,
            'category_stats': PostCategorySerializer(category_stats, many=True).data
        })

    @action(detail=False, methods=['get'])
    def home_posts(self, request):
        """获取首页推文列表 - 简单的时间序 + 热度混合排序"""
        # 获取分页参数
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 10))

        # 基础查询 - 已审核通过的帖子，按发布时间和热度混合排序
        posts_queryset = Post.objects.filter(
            status='approved'
        ).select_related('author', 'category').prefetch_related('medias').order_by(
            '-is_featured',  # 精选帖子优先
            '-is_top',  # 置顶帖子优先
            '-hot_score',  # 热度分数
            '-published_at'  # 发布时间
        )

        # 排除被当前用户拉黑的用户的帖子
        if request.user.is_authenticated:
            blocked_users = BlockedUser.objects.filter(
                user=request.user
            ).values_list('blocked_user', flat=True)
            if blocked_users:
                posts_queryset = posts_queryset.exclude(author__in=blocked_users)

        # 分页处理
        from django.core.paginator import Paginator
        paginator = Paginator(posts_queryset, page_size)

        try:
            posts_page = paginator.page(page)
        except:
            posts_page = paginator.page(1)

        # 序列化数据
        serializer = PostListSerializer(posts_page.object_list, many=True, context={'request': request})

        # 构建响应数据
        response_data = {
            'success': True,
            'data': {
                'posts': serializer.data,
                'pagination': {
                    'current_page': posts_page.number,
                    'total_pages': paginator.num_pages,
                    'total_count': paginator.count,
                    'has_next': posts_page.has_next(),
                    'has_previous': posts_page.has_previous(),
                    'page_size': page_size
                }
            }
        }

        return Response(response_data)

    @action(detail=False, methods=['get'])
    def pet_care_tips(self, request):
        """宠物护理小贴士"""
        tips_posts = Post.objects.filter(
            status='approved',
            category__name__in=['护理知识', '健康指南', '饲养技巧'],
            is_featured=True
        ).select_related('author', 'category')[:10]

        serializer = PostListSerializer(tips_posts, many=True, context={'request': request})
        return Response({'tips': serializer.data})

    @action(detail=False, methods=['get'])
    def pet_adoption(self, request):
        """宠物领养信息"""
        adoption_posts = Post.objects.filter(
            status='approved',
            category__name='领养信息'
        ).select_related('author', 'category').order_by('-published_at')[:20]

        serializer = PostListSerializer(adoption_posts, many=True, context={'request': request})
        return Response({'adoptions': serializer.data})


# ===== 统计相关视图 =====
class StatisticsView(APIView):
    """社区统计视图"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request):
        """获取社区统计数据"""
        # 基础统计
        total_users = User.objects.filter(is_active=True).count()
        total_posts = Post.objects.filter(status='approved').count()
        total_comments = Comment.objects.filter(is_deleted=False).count()
        total_topics = Topic.objects.filter(status='approved').count()

        # 今日统计
        today = timezone.now().date()
        today_posts = Post.objects.filter(
            published_at__date=today,
            status='approved'
        ).count()

        today_users = User.objects.filter(
            date_joined__date=today
        ).count()

        # 活跃度统计
        active_users = User.objects.filter(
            last_login__gte=timezone.now() - timedelta(days=7),
            is_active=True
        ).count()

        return Response({
            'total_stats': {
                'users': total_users,
                'posts': total_posts,
                'comments': total_comments,
                'topics': total_topics
            },
            'today_stats': {
                'posts': today_posts,
                'users': today_users
            },
            'active_users': active_users
        })


# ===== WebSocket相关视图（可选）=====
class RealtimeView(APIView):
    """实时功能相关"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """获取实时数据"""
        # 获取用户的实时通知
        recent_notifications = Notification.objects.filter(
            receiver=request.user,
            is_read=False,
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).order_by('-created_at')[:5]

        return Response({
            'notifications': NotificationSerializer(recent_notifications, many=True).data,
            'timestamp': timezone.now().isoformat()
        })