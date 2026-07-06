# -*- coding: utf-8 -*-
import re

from django.db import transaction
from django.db.models import F, Q, Count, Sum, Prefetch
from django.utils import timezone
from django.utils.text import slugify
from django.db import IntegrityError
import uuid
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import timedelta
from django.db.models.functions import TruncDate
from rest_framework import status, permissions, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet, ViewSet, GenericViewSet
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from community.models import (
    Post, PostCategory, Comment, Topic, UserAction,
    Report, Notification, UserFollow, PostCollection, BlockedUser,
    PostView, ReviewLog, PostTopic, SensitiveWord, PostMedia,
)
from community.serializers import (
    # 基础
    BasicUserSerializer, UserDetailSerializer, BasicManagerSerializer,
    # 分类 / 媒体 / 话题
    PostCategorySerializer, PostMediaSerializer,
    TopicSerializer, SimpleTopicSerializer,
    # 评论
    CommentSerializer, CreateCommentSerializer, AdminCommentSerializer,
    # 帖子（用户端）
    PostListSerializer, PostDetailSerializer,
    CreatePostSerializer, UpdatePostSerializer,
    # 帖子（管理端）
    AdminPostListSerializer, AdminPostDetailSerializer,
    # 其他
    UserActionSerializer, PostCollectionSerializer,
    UserFollowSerializer, ReportSerializer, ReportAdminSerializer,
    NotificationSerializer, PostViewHistorySerializer, AdminCreatePostSerializer,
)
from community.filters import (
    PostFilter, CommentFilter, UserFilter, TopicFilter,
    PostCategoryFilter, NotificationFilter, ReportFilter,
    AdminPostFilter, apply_filters,
)
from community.pagination import paginate_queryset, create_paginated_response
from user.models import User
from utils.authentication import UserAuthentication, ManagerAuthentication
from utils.permission import IsUser, IsManager, IsAuthorOrReadOnly


# ======================================================================
# 基础视图类
# ======================================================================

class BaseViewSet(ModelViewSet):
    """
    基础视图集 — 用户端通用功能
    · 自动注入 author / user
    · 自动排除被拉黑用户的内容
    · 统一分页
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [IsUser()]
        return [IsAuthenticatedOrReadOnly()]

    def perform_create(self, serializer):
        model = serializer.Meta.model
        if hasattr(model, 'author'):
            serializer.save(author=self.request.user)
        elif hasattr(model, 'user'):
            serializer.save(user=self.request.user)
        else:
            serializer.save()

    def get_queryset(self):
        queryset = super().get_queryset()

        # 应用过滤器
        filterset_class = getattr(self, 'filterset_class', None)
        if filterset_class:
            queryset = apply_filters(queryset, self.request, filterset_class)

        # 排除被拉黑用户的内容
        if isinstance(self.request.user, User) and self.request.user.is_authenticated:
            blocked = BlockedUser.objects.filter(
                user=self.request.user
            ).values_list('blocked_user', flat=True)
            if hasattr(queryset.model, 'author'):
                queryset = queryset.exclude(author__in=blocked)
            elif hasattr(queryset.model, 'user'):
                queryset = queryset.exclude(user__in=blocked)

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        pagination_type = request.GET.get('pagination_type', 'standard')
        paginated, paginator = paginate_queryset(queryset, request, pagination_type)
        serializer = self.get_serializer(paginated, many=True)
        return create_paginated_response(serializer.data, paginator)


# ======================================================================
# 用户
# ======================================================================

class UserViewSet(ReadOnlyModelViewSet):
    """用户视图 — 支持 id 或 username 查询"""
    queryset = User.objects.filter(is_active=True)
    serializer_class = UserDetailSerializer
    filterset_class = UserFilter
    authentication_classes = [UserAuthentication]
    permission_classes = [permissions.AllowAny]
    lookup_field = 'username'

    def get_object(self):
        lookup = self.kwargs.get(self.lookup_field)
        if lookup == 'me':
            user = self.request.user
            if not (isinstance(user, User) and user.is_authenticated):
                from rest_framework.exceptions import NotFound
                raise NotFound('用户不存在')
            self.check_object_permissions(self.request, user)
            return user
        try:
            qs = User.objects.filter(is_active=True)
            user = qs.get(id=int(lookup)) if lookup.isdigit() else qs.get(username=lookup)
            self.check_object_permissions(self.request, user)
            return user
        except User.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound('用户不存在')

    def get_serializer_class(self):
        if self.action == 'list':
            return BasicUserSerializer
        return UserDetailSerializer

    # ---------- 帖子 ----------
    @action(detail=True, methods=['get'])
    def posts(self, request, username=None):
        user = self.get_object()
        posts = (
            Post.objects.filter(author=user, status='approved')
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-published_at')
        )
        paginated, paginator = paginate_queryset(posts, request, 'user_content')
        serializer = PostListSerializer(paginated, many=True, context={'request': request})
        return create_paginated_response(serializer.data, paginator)

    # ---------- 收藏 ----------
    @action(detail=True, methods=['get'], permission_classes=[IsUser])
    def collections(self, request, username=None):
        user = self.get_object()
        if user != request.user:
            return Response({'detail': '无权访问'}, status=status.HTTP_403_FORBIDDEN)

        qs = (
            PostCollection.objects.filter(user=user, post__is_deleted=False)  # ← 作者已删的帖子不再出现在收藏里
            .select_related('post__author', 'post__category')
            .prefetch_related('post__medias', 'post__post_topics__topic')
            .order_by('-created_at')
        )
        paginated, paginator = paginate_queryset(qs, request, 'standard')
        serializer = PostCollectionSerializer(paginated, many=True, context={'request': request})
        return create_paginated_response(serializer.data, paginator)
    # ---------- 关注 / 取消关注 ----------
    @action(detail=True, methods=['post'], permission_classes=[IsUser])
    def follow(self, request, username=None):
        target = self.get_object()
        if target == request.user:
            return Response({'detail': '不能关注自己'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            relation = UserFollow.objects.filter(
                follower=request.user, following=target
            ).first()
            if relation:
                relation.delete()
                # ① 反向关系的 is_mutual 复位
                UserFollow.objects.filter(
                    follower=target, following=request.user
                ).update(is_mutual=False)
                # ② 删掉旧的 follow_user，避免再次关注撞唯一约束
                UserAction.objects.filter(
                    user=request.user, action_type='follow_user', target_user=target
                ).delete()
                return Response({'detail': '已取消关注', 'followed': False})

            UserFollow.objects.create(follower=request.user, following=target)
            UserAction.objects.get_or_create(
                user=request.user, action_type='follow_user', target_user=target
            )
            return Response({'detail': '关注成功', 'followed': True})
    # ---------- 拉黑 / 取消拉黑 ----------
    @action(detail=True, methods=['post'], permission_classes=[IsUser])
    def block(self, request, username=None):
        target = self.get_object()
        if target == request.user:
            return Response({'detail': '不能拉黑自己'}, status=status.HTTP_400_BAD_REQUEST)

        blocked, created = BlockedUser.objects.get_or_create(
            user=request.user, blocked_user=target,
            defaults={'reason': request.data.get('reason', '')}
        )
        if not created:
            blocked.delete()
            return Response({'detail': '已取消拉黑', 'blocked': False})

        # 互相取消关注
        UserFollow.objects.filter(
            Q(follower=request.user, following=target)
            | Q(follower=target, following=request.user)
        ).delete()
        return Response({'detail': '拉黑成功', 'blocked': True})

    # ---------- 统计 ----------
    @action(detail=True, methods=['get'])
    def stats(self, request, username=None):
        user = self.get_object()

        approved_posts = Post.objects.filter(author=user, status='approved')
        post_likes = approved_posts.aggregate(t=Sum('like_count'))['t'] or 0
        comment_likes = (
            Comment.objects.filter(author=user, is_deleted=False)
            .aggregate(t=Sum('like_count'))['t'] or 0
        )

        return Response({
            'success': True,
            'data': {
                'user_id': user.id,
                'username': user.username,
                'followers_count': UserFollow.objects.filter(following=user).count(),
                'following_count': UserFollow.objects.filter(follower=user).count(),
                'total_likes': post_likes + comment_likes,
                'posts_count': approved_posts.count(),
                'comments_count': Comment.objects.filter(author=user, is_deleted=False).count(),
                'collections_count': PostCollection.objects.filter(user=user).count(),
                'total_views': approved_posts.aggregate(t=Sum('view_count'))['t'] or 0,
            }
        })

    # ---------- 关注列表 ----------
    @action(detail=True, methods=['get'])
    def following_list(self, request, username=None):
        user = self.get_object()
        qs = (
            UserFollow.objects.filter(follower=user)
            .select_related('following')
            .order_by('-created_at')
        )
        paginated, paginator = paginate_queryset(qs, request, 'standard')
        serializer = UserFollowSerializer(
            paginated, many=True, context={'request': request, 'type': 'following'}
        )
        return create_paginated_response(serializer.data, paginator)

    # ---------- 粉丝列表 ----------
    @action(detail=True, methods=['get'])
    def followers_list(self, request, username=None):
        user = self.get_object()
        qs = (
            UserFollow.objects.filter(following=user)
            .select_related('follower')
            .order_by('-created_at')
        )
        paginated, paginator = paginate_queryset(qs, request, 'standard')
        serializer = UserFollowSerializer(
            paginated, many=True, context={'request': request, 'type': 'followers'}
        )
        return create_paginated_response(serializer.data, paginator)

    # ---------- 完整资料（详情页一次拉齐）----------
    @action(detail=True, methods=['get'])
    def profile(self, request, username=None):
        user = self.get_object()
        user_data = UserDetailSerializer(user, context={'request': request}).data

        approved_posts = Post.objects.filter(author=user, status='approved')
        stats_data = {
            'followers_count': UserFollow.objects.filter(following=user).count(),
            'following_count': UserFollow.objects.filter(follower=user).count(),
            'posts_count': approved_posts.count(),
            'total_likes': (
                (approved_posts.aggregate(t=Sum('like_count'))['t'] or 0)
                + (Comment.objects.filter(author=user, is_deleted=False)
                   .aggregate(t=Sum('like_count'))['t'] or 0)
            ),
        }

        recent = (
            approved_posts.select_related('category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-published_at')[:10]
        )
        posts_data = PostListSerializer(recent, many=True, context={'request': request}).data

        return Response({
            'success': True,
            'data': {'user': user_data, 'stats': stats_data, 'recent_posts': posts_data}
        })


# ======================================================================
# 帖子分类
# ======================================================================

class PostCategoryViewSet(ReadOnlyModelViewSet):
    queryset = PostCategory.objects.filter(is_active=True).order_by('sort_order')
    serializer_class = PostCategorySerializer
    filterset_class = PostCategoryFilter
    authentication_classes = [UserAuthentication]
    permission_classes = [permissions.AllowAny]

    @action(detail=True, methods=['get'])
    def posts(self, request, pk=None):
        category = self.get_object()
        posts = (
            Post.objects.filter(category=category, status='approved')
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-hot_score')
        )
        posts = apply_filters(posts, request, PostFilter)
        paginated, paginator = paginate_queryset(posts, request, 'standard')
        serializer = PostListSerializer(paginated, many=True, context={'request': request})
        return create_paginated_response(serializer.data, paginator)


# ======================================================================
# 话题
# ======================================================================

class TopicViewSet(ReadOnlyModelViewSet):
    queryset = Topic.objects.filter(status='approved')
    serializer_class = TopicSerializer
    filterset_class = TopicFilter
    authentication_classes = [UserAuthentication]
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    def get_serializer_class(self):
        return SimpleTopicSerializer if self.action == 'list' else TopicSerializer

    @action(detail=False, methods=['post'], url_path='create', permission_classes=[IsUser])
    def create_topic(self, request):
        name = (request.data.get('name') or '').strip().lstrip('#').strip()
        if not name:
            return Response({'detail': '请输入话题名称'}, status=status.HTTP_400_BAD_REQUEST)
        if len(name) > 50:
            return Response({'detail': '话题名称不能超过 50 字'}, status=status.HTTP_400_BAD_REQUEST)

        # 先搜：同名话题是否已存在（含所有状态 / 软删）
        existing = Topic.all_objects.filter(name=name).first()
        if existing:
            if existing.status == 'banned':
                return Response({'detail': '该话题已被封禁，不可使用'}, status=status.HTTP_400_BAD_REQUEST)
            if existing.is_deleted or existing.status in ('rejected', 'suspended'):
                return Response({'detail': '该话题暂不可用'}, status=status.HTTP_400_BAD_REQUEST)
            # 已存在且可用（pending / approved 等）→ 直接复用，不建重复
            return Response(SimpleTopicSerializer(existing).data)

        # 不存在 → 新建，状态 pending：随帖子一起审核，不预先放行
        base = slugify(name, allow_unicode=True)[:40] or f'topic-{uuid.uuid4().hex[:8]}'
        slug = base
        if Topic.all_objects.filter(slug=slug).exists():
            slug = f'{base[:33]}-{uuid.uuid4().hex[:6]}'

        try:
            topic = Topic.objects.create(
                name=name,
                slug=slug,
                creator=request.user,
                status='pending',
            )
        except IntegrityError:
            # 并发下被别人抢先建了 → 复用，但要重新判一次封禁
            topic = Topic.all_objects.filter(name=name).first()
            if not topic or topic.status == 'banned' or topic.is_deleted \
                    or topic.status in ('rejected', 'suspended'):
                return Response({'detail': '该话题暂不可用'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SimpleTopicSerializer(topic).data, status=status.HTTP_201_CREATED)
    @action(detail=True, methods=['get'])
    def posts(self, request, slug=None):
        topic = self.get_object()
        posts = (
            Post.objects.filter(post_topics__topic=topic, status='approved')
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-published_at')
        )
        posts = apply_filters(posts, request, PostFilter)
        paginated, paginator = paginate_queryset(posts, request, 'standard')
        serializer = PostListSerializer(paginated, many=True, context={'request': request})
        return create_paginated_response(serializer.data, paginator)

    @action(detail=True, methods=['post'], permission_classes=[IsUser])
    def follow(self, request, slug=None):
        topic = self.get_object()
        exists = UserAction.objects.filter(
            user=request.user, action_type='follow_topic', topic=topic
        ).exists()

        if exists:
            UserAction.objects.filter(
                user=request.user, action_type='follow_topic', topic=topic
            ).delete()
            return Response({'detail': '已取消关注', 'followed': False})

        UserAction.objects.create(
            user=request.user, action_type='follow_topic', topic=topic
        )
        return Response({'detail': '关注成功', 'followed': True})


# ======================================================================
# 帖子（用户端）
# ======================================================================

class PostViewSet(BaseViewSet):
    queryset = (
        Post.objects.select_related('author', 'category')
        .prefetch_related('medias', 'post_topics__topic')
    )
    filterset_class = PostFilter
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsAuthorOrReadOnly()]
        if self.action in ('create', 'like', 'collect', 'share', 'report', 'feed', 'my_posts'):
            return [IsUser()]
        return [IsAuthenticatedOrReadOnly()]

    def get_serializer_class(self):
        if self.action == 'list':
            return PostListSerializer
        if self.action == 'create':
            return CreatePostSerializer
        if self.action in ('update', 'partial_update'):
            return UpdatePostSerializer
        return PostDetailSerializer

    def get_queryset(self):
        queryset = super().get_queryset()

        if self.action == 'list':
            queryset = queryset.filter(status='approved')

        if self.action == 'retrieve':
            user = self.request.user
            if isinstance(user, User) and user.is_authenticated:
                # 允许作者看自己未过审的帖；其他人只能看 approved
                queryset = queryset.filter(Q(status='approved') | Q(author=user))
            else:
                queryset = queryset.filter(status='approved')

        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        pid = instance.pk

        if isinstance(request.user, User) and request.user.is_authenticated:
            _, created = PostView.objects.get_or_create(user=request.user, post_id=pid)
            if not created:
                PostView.objects.filter(user=request.user, post_id=pid).update(
                    view_count=F('view_count') + 1,
                    updated_at=timezone.now(),   # 关键：.update() 不触发 auto_now，手动刷新供「浏览历史」按最近浏览排序
                )
        Post.objects.filter(pk=pid).update(view_count=F('view_count') + 1)

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def perform_create(self, serializer):
        post = serializer.save(author=self.request.user)
        self._grant_create_reward(post)

    def _grant_create_reward(self, post):
        import logging
        from django.db import transaction
        logger = logging.getLogger(__name__)
        try:
            from wallet.models import UserWallet, WalletTransaction
            with transaction.atomic():
                wallet, _ = UserWallet.objects.get_or_create(user_id=self.request.user.id)
                wallet.change_points(
                    amount=10,
                    action=WalletTransaction.Action.ACTIVITY_REWARD,
                    operator_id=self.request.user.id,
                    operator_role='system',
                    related_type='post',
                    related_id=post.pk,
                    remark='发帖奖励 +10',
                    idempotent_key=f'post_create_reward_{post.pk}',
                )
        except Exception:
            logger.exception('grant create reward failed: post=%s', post.pk)

    def perform_destroy(self, instance):
        instance.soft_delete()

    # ---------- 点赞 ----------
    @action(detail=True, methods=['post'])
    def like(self, request, pk=None):
        post = self.get_object()
        with transaction.atomic():
            ua, created = UserAction.objects.get_or_create(
                user=request.user, action_type='like_post', post=post
            )
            if not created:
                ua.delete()
                Post.objects.filter(id=post.id).update(like_count=F('like_count') - 1)
                return Response({'detail': '已取消点赞', 'liked': False})

            Post.objects.filter(id=post.id).update(like_count=F('like_count') + 1)
            if post.author_id != request.user.id:
                Notification.objects.create(
                    receiver=post.author, sender=request.user,
                    notification_type='like_post',
                    title='收到新点赞',
                    content=f'{request.user.username} 赞了你的帖子',
                    post=post,
                )
            return Response({'detail': '点赞成功', 'liked': True})
    # ---------- 收藏 ----------
    @action(detail=True, methods=['post'])
    def collect(self, request, pk=None):
        post = self.get_object()
        collection, created = PostCollection.objects.get_or_create(
            user=request.user, post=post,
            defaults={
                'folder': request.data.get('folder', '默认收藏夹'),
                'note': request.data.get('note', ''),
            }
        )
        with transaction.atomic():
            if not created:
                collection.delete()
                Post.objects.filter(id=post.id).update(collect_count=F('collect_count') - 1)
                return Response({'detail': '已取消收藏', 'collected': False})
            Post.objects.filter(id=post.id).update(collect_count=F('collect_count') + 1)
            return Response({'detail': '收藏成功', 'collected': True})

    # ---------- 分享 ----------
    @action(detail=True, methods=['post'])
    def share(self, request, pk=None):
        post = self.get_object()
        UserAction.objects.create(user=request.user, action_type='share_post', post=post)
        Post.objects.filter(id=post.id).update(share_count=F('share_count') + 1)
        return Response({'detail': '分享成功'})

    # ---------- 热门 ----------
    @action(detail=False, methods=['get'])
    def trending(self, request):
        posts = (
            Post.objects.filter(status='approved')
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-hot_score', '-like_count')
        )
        paginated, paginator = paginate_queryset(posts, request, 'standard')
        serializer = PostListSerializer(paginated, many=True, context={'request': request})
        return create_paginated_response(serializer.data, paginator)

    # ---------- 关注动态 ----------
    @action(detail=False, methods=['get'])
    def feed(self, request):
        following_ids = UserFollow.objects.filter(
            follower=request.user
        ).values_list('following', flat=True)

        posts = (
            Post.objects.filter(author__in=following_ids, status='approved')
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-published_at')
        )
        paginated, paginator = paginate_queryset(posts, request, 'standard')
        serializer = PostListSerializer(paginated, many=True, context={'request': request})
        return create_paginated_response(serializer.data, paginator)

    # ---------- 我的帖子 ----------
    @action(detail=False, methods=['get'])
    def my_posts(self, request):
        posts = (
            Post.objects.filter(author=request.user)
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-created_at')
        )
        status_param = request.query_params.get('status')
        if status_param and status_param != 'all':
            posts = posts.filter(status=status_param)

        user_stats = posts.aggregate(
            total_posts=Count('id'),
            total_views=Sum('view_count'),
            total_likes=Sum('like_count'),
            total_comments=Sum('comment_count'),
        )

        paginated, paginator = paginate_queryset(posts, request, 'standard')
        serializer = PostListSerializer(paginated, many=True, context={'request': request})
        response = create_paginated_response(serializer.data, paginator)

        if isinstance(response, Response):
            response.data['user_stats'] = {
                k: v or 0 for k, v in user_stats.items()
            }
        return response

    # ---------- 举报帖子 ----------
    @action(detail=True, methods=['post'])
    def report(self, request, pk=None):
        post = self.get_object()

        if Report.objects.filter(
            reporter=request.user, content_type='post', content_id=post.id
        ).exists():
            return Response({'detail': '您已经举报过该帖子'}, status=status.HTTP_400_BAD_REQUEST)

        report_type = request.data.get('report_type')
        reason = request.data.get('reason')
        if not report_type or not reason:
            return Response({'detail': '请提供举报类型和理由'}, status=status.HTTP_400_BAD_REQUEST)

        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        ip = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')

        rpt = Report.objects.create(
            reporter=request.user,
            content_type='post', content_id=post.id,
            report_type=report_type, reason=reason,
            evidence=request.data.get('evidence', []),
            ip_address=ip,
        )
        Post.objects.filter(id=post.id).update(report_count=F('report_count') + 1)
        return Response(
            {'detail': '举报成功，我们会尽快处理', 'report_id': rpt.id},
            status=status.HTTP_201_CREATED,
        )


# ======================================================================
# 评论
# ======================================================================

class CommentViewSet(BaseViewSet):
    queryset = (
        Comment.objects.filter(is_deleted=False)
        .select_related('author', 'post')
        .prefetch_related(
            Prefetch(
                'replies',
                queryset=Comment.objects.filter(is_deleted=False)
                .select_related('author').order_by('-created_at'),
                to_attr='active_replies',
            )
        )
    )
    serializer_class = CommentSerializer
    filterset_class = CommentFilter
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy'):
            return [IsAuthorOrReadOnly()]
        if self.action in ('create', 'like'):
            return [IsUser()]
        return [IsAuthenticatedOrReadOnly()]

    def get_serializer_class(self):
        return CreateCommentSerializer if self.action == 'create' else CommentSerializer

    def perform_create(self, serializer):
        comment = serializer.save(author=self.request.user)

        # 帖子评论数 +1
        Post.objects.filter(id=comment.post_id).update(comment_count=F('comment_count') + 1)

        # 父评论回复数 +1
        if comment.parent_id:
            Comment.objects.filter(id=comment.parent_id).update(reply_count=F('reply_count') + 1)

        # 通知
        if comment.parent:
            if comment.parent.author_id != self.request.user.id:
                Notification.objects.create(
                    receiver=comment.parent.author, sender=self.request.user,
                    notification_type='reply_comment',
                    title='收到新回复',
                    content=f'{self.request.user.username} 回复了你的评论',
                    post=comment.post, comment=comment,
                )
        else:
            if comment.post.author_id != self.request.user.id:
                Notification.objects.create(
                    receiver=comment.post.author, sender=self.request.user,
                    notification_type='comment_post',
                    title='收到新评论',
                    content=f'{self.request.user.username} 评论了你的帖子',
                    post=comment.post, comment=comment,
                )

    def perform_destroy(self, instance):
        post_id = instance.post_id
        parent_id = instance.parent_id
        instance.soft_delete()
        Post.objects.filter(id=post_id).update(comment_count=F('comment_count') - 1)
        if parent_id:
            Comment.objects.filter(id=parent_id).update(reply_count=F('reply_count') - 1)

    @action(detail=True, methods=['post'])
    def like(self, request, pk=None):
        comment = self.get_object()
        exists = UserAction.objects.filter(
            user=request.user, action_type='like_comment', comment=comment
        ).exists()

        with transaction.atomic():
            if exists:
                UserAction.objects.filter(
                    user=request.user, action_type='like_comment', comment=comment
                ).delete()
                Comment.objects.filter(id=comment.id).update(like_count=F('like_count') - 1)
                return Response({'detail': '已取消点赞', 'liked': False})

            UserAction.objects.create(
                user=request.user, action_type='like_comment', comment=comment
            )
            Comment.objects.filter(id=comment.id).update(like_count=F('like_count') + 1)
            return Response({'detail': '点赞成功', 'liked': True})


# ======================================================================
# 用户行为记录
# ======================================================================

class UserActionViewSet(ReadOnlyModelViewSet):
    serializer_class = UserActionSerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def get_queryset(self):
        return (
            UserAction.objects.filter(user=self.request.user)
            .select_related('post', 'comment', 'topic', 'target_user')
            .order_by('-created_at')
        )


# ======================================================================
# 通知
# ======================================================================

class NotificationViewSet(ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    filterset_class = NotificationFilter
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def get_queryset(self):
        return (
            Notification.objects.filter(receiver=self.request.user)
            .select_related('sender', 'post', 'comment')
            .order_by('-created_at')
        )

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_as_read()
        return Response({'detail': '已标记为已读'})

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        Notification.objects.filter(
            receiver=request.user, is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return Response({'detail': '全部已标记为已读'})

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        count = Notification.objects.filter(receiver=request.user, is_read=False).count()
        return Response({'unread_count': count})


# ======================================================================
# 浏览历史（仅本人）
# ======================================================================

class PostHistoryViewSet(
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    GenericViewSet,
):
    """
    浏览历史 —— 仅本人可见，按帖子去重（每帖一条，记累计浏览次数 + 最近浏览时间）
    · GET    /community/history/            列表（最近浏览在前）
    · DELETE /community/history/{id}/       删除单条
    · POST   /community/history/clear/      清空全部
    """
    serializer_class = PostViewHistorySerializer
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def get_queryset(self):
        # 历史是「能点开就显示」的临时数据：作者软删 / 未过审的帖子直接不进历史，避免死链
        return (
            PostView.objects
            .filter(user=self.request.user, post__is_deleted=False, post__status='approved')
            .select_related('post__author', 'post__category')
            .prefetch_related('post__medias', 'post__post_topics__topic')
            .order_by('-updated_at')   # 依赖上面 retrieve 里手动刷新的 updated_at
        )

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        paginated, paginator = paginate_queryset(qs, request, 'standard')
        serializer = self.get_serializer(paginated, many=True)
        return create_paginated_response(serializer.data, paginator)

    @action(detail=False, methods=['post', 'delete'])
    def clear(self, request):
        deleted, _ = PostView.objects.filter(user=request.user).delete()
        return Response({'detail': '已清空浏览历史', 'deleted': deleted})
# ======================================================================
# 举报（用户端）
# ======================================================================

class ReportViewSet(BaseViewSet):
    """
    普通用户：提交举报（create）、查看自己的举报（list/retrieve）。
    提交后不可改 / 删。
    """
    queryset = Report.objects.select_related('reporter', 'handler').all()
    serializer_class = ReportSerializer
    filterset_class = ReportFilter
    http_method_names = ['get', 'post', 'head', 'options']

    def get_permissions(self):
        return [IsUser()]

    def get_queryset(self):
        return super().get_queryset().filter(reporter=self.request.user)


# ======================================================================
# 搜索
# ======================================================================

class SearchView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        query = request.GET.get('q', '')
        search_type = request.GET.get('type', 'all')
        results = {}

        if search_type in ('all', 'post'):
            posts = (
                Post.objects.filter(
                    Q(title__icontains=query) | Q(content__icontains=query),
                    status='approved',
                )
                .select_related('author', 'category')
                .prefetch_related('medias', 'post_topics__topic')[:10]
            )
            results['posts'] = PostListSerializer(
                posts, many=True, context={'request': request}
            ).data

        if search_type in ('all', 'user'):
            users = User.objects.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query),
                is_active=True,
            )[:10]
            results['users'] = BasicUserSerializer(users, many=True).data

        if search_type in ('all', 'topic'):
            topics = Topic.objects.filter(
                Q(name__icontains=query) | Q(description__icontains=query),
                status='approved',
            )[:10]
            results['topics'] = SimpleTopicSerializer(topics, many=True).data

        return Response(results)


# ======================================================================
# 管理员 — 帖子审核
# ======================================================================

class AdminPostViewSet(ModelViewSet):
    """
    管理员帖子审核
    · 用 AdminPost 系列序列化器，不触发 UserAction / PostCollection 查询
    · reviewer FK 已指向 Manager，直接赋值 request.user
    """
    queryset = Post.all_objects.all()
    filterset_class = AdminPostFilter
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    def get_serializer_class(self):
        if self.action == 'list':
            return AdminPostListSerializer
        return AdminPostDetailSerializer

    def get_queryset(self):
        return (
            Post.all_objects
            .select_related('author', 'category', 'reviewer')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-created_at')
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        queryset = apply_filters(queryset, request, self.filterset_class)
        paginated, paginator = paginate_queryset(queryset, request, 'admin')
        serializer = self.get_serializer(paginated, many=True)
        return create_paginated_response(serializer.data, paginator)

    # ---------- 审核通过 ----------
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        post = self.get_object()
        old_status = post.status

        with transaction.atomic():
            post.status = 'approved'
            post.reviewer = request.user
            post.reviewed_at = timezone.now()
            if not post.published_at:
                post.published_at = timezone.now()
                post.last_active_at = timezone.now()
            post.review_note = request.data.get('note', '')
            post.save(update_fields=[
                'status', 'reviewer', 'reviewed_at',
                'published_at', 'last_active_at', 'review_note', 'updated_at',
            ])

            # 帖子过审 → 关联的待审核话题一并转正
            Topic.objects.filter(topic_posts__post=post, status='pending').update(
                status='approved',
                reviewer=request.user,
                reviewed_at=timezone.now(),
                updated_at=timezone.now(),
            )

            ReviewLog.objects.create(
                content_type='post', content_id=post.id,
                reviewer=request.user,
                action='manual_approve',
                old_status=old_status, new_status='approved',
                note=request.data.get('note', ''),
            )

            Notification.objects.create(
                receiver=post.author,
                notification_type='post_approved',
                title='帖子审核通过',
                content=f'你的帖子《{post.title}》审核通过了',
                post=post,
            )

        return Response({'detail': '审核通过'})
    # ---------- 审核拒绝 ----------
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        post = self.get_object()
        reason = request.data.get('reason', '不符合社区规范')
        old_status = post.status

        # 违规与话题相关时：ban_topics=true 封禁本帖全部话题，
        # 或 ban_topic_ids=[...] 精确封禁其中几个
        ban_topics = bool(request.data.get('ban_topics', False))
        ban_topic_ids = request.data.get('ban_topic_ids') or []

        with transaction.atomic():
            post.status = 'rejected'
            post.reviewer = request.user
            post.reviewed_at = timezone.now()
            post.reject_reason = reason
            post.review_note = request.data.get('note', '')
            post.save(update_fields=[
                'status', 'reviewer', 'reviewed_at',
                'reject_reason', 'review_note', 'updated_at',
            ])

            # ===== 封禁关联话题（只动挂在本帖上的话题）=====
            if ban_topics or ban_topic_ids:
                tq = Topic.objects.filter(topic_posts__post=post)
                if ban_topic_ids:
                    tq = tq.filter(id__in=ban_topic_ids)
                to_ban = list(tq.exclude(status='banned'))

                if to_ban:
                    banned_ids = [t.id for t in to_ban]
                    now = timezone.now()

                    Topic.objects.filter(id__in=banned_ids).update(
                        status='banned',
                        reviewer=request.user,
                        reviewed_at=now,
                        updated_at=now,
                    )
                    for t in to_ban:
                        ReviewLog.objects.create(
                            content_type='topic', content_id=t.id,
                            reviewer=request.user, action='ban',
                            old_status=t.status, new_status='banned',
                            reason=reason,
                            note=f'随帖子 #{post.id} 审核拒绝一并封禁',
                        )

                    # ===== 级联：引用这些话题的其它待审核帖子一并打回 =====
                    affected = list(
                        Post.objects.filter(
                            post_topics__topic_id__in=banned_ids,
                            status__in=['pending', 'reviewing'],
                        )
                        .exclude(id=post.id)
                        .distinct()
                        .select_related('author')
                    )
                    if affected:
                        cascade_reason = '所含话题因违规被封禁，帖子一并下架'
                        Post.objects.filter(id__in=[p.id for p in affected]).update(
                            status='rejected',
                            reviewer=request.user,
                            reject_reason=cascade_reason,
                            reviewed_at=now,
                            updated_at=now,
                        )
                        for p in affected:
                            ReviewLog.objects.create(
                                content_type='post', content_id=p.id,
                                reviewer=request.user,
                                action='manual_reject',
                                old_status=p.status, new_status='rejected',
                                reason=cascade_reason,
                                note=f'因话题封禁联动（触发帖 #{post.id}）',
                            )
                            Notification.objects.create(
                                receiver=p.author,
                                notification_type='post_rejected',
                                title='帖子审核未通过',
                                content=f'你的帖子《{p.title}》所含话题已被封禁，未能通过审核',
                                post=p,
                            )

            ReviewLog.objects.create(
                content_type='post', content_id=post.id,
                reviewer=request.user,
                action='manual_reject',
                old_status=old_status, new_status='rejected',
                reason=reason,
                note=request.data.get('note', ''),
            )

            Notification.objects.create(
                receiver=post.author,
                notification_type='post_rejected',
                title='帖子审核未通过',
                content=f'你的帖子《{post.title}》审核未通过，原因: {reason}',
                post=post,
            )

        return Response({'detail': '审核拒绝'})
    # ---------- 隐藏 ----------
    @action(detail=True, methods=['post'])
    def hide(self, request, pk=None):
        post = self.get_object()
        old_status = post.status

        with transaction.atomic():
            post.status = 'hidden'
            post.reviewer = request.user
            post.reviewed_at = timezone.now()
            post.save(update_fields=['status', 'reviewer', 'reviewed_at', 'updated_at'])

            ReviewLog.objects.create(
                content_type='post', content_id=post.id,
                reviewer=request.user,
                action='hide',
                old_status=old_status, new_status='hidden',
                reason=request.data.get('reason', ''),
                note=request.data.get('note', ''),
            )

        return Response({'detail': '已隐藏', 'status': 'hidden'})

    # ---------- 精选 ----------
    @action(detail=True, methods=['post'])
    def feature(self, request, pk=None):
        post = self.get_object()
        post.is_featured = not post.is_featured
        post.save(update_fields=['is_featured', 'updated_at'])  # 仍触发精选奖励，且不覆盖计数
        return Response({'detail': '精选状态已更新', 'is_featured': post.is_featured})

    # ---------- 置顶 ----------
    @action(detail=True, methods=['post'])
    def top(self, request, pk=None):
        post = self.get_object()
        new_top = not post.is_top
        Post.all_objects.filter(pk=post.pk).update(is_top=new_top)
        return Response({'detail': '置顶状态已更新', 'is_top': new_top})


    @action(detail=False, methods=['post'], url_path='create-by-admin')
    def create_by_admin(self, request):
        author = User.objects.get(id=2)

        data = request.data.copy()
        medias_data = data.pop('medias', [])
        topic_ids = data.pop('topic_ids', [])

        post = Post.objects.create(
            author=author,
            category_id=data.get('category') or None,
            post_type=data.get('post_type') or 'image',
            title=data.get('title', '').strip(),
            content=data.get('content', '').strip(),
            cover_image=data.get('cover_image', ''),
            location=data.get('location', ''),
            latitude=data.get('latitude') or None,
            longitude=data.get('longitude') or None,
            status=data.get('status') or 'approved',
            is_featured=bool(data.get('is_featured', False)),
            is_top=bool(data.get('is_top', False)),
            reviewer=request.user,
            reviewed_at=timezone.now(),
        )

        if post.status == 'approved':
            post.published_at = timezone.now()
            post.last_active_at = timezone.now()
            post.save(update_fields=['published_at', 'last_active_at', 'updated_at'])

        for index, media in enumerate(medias_data):
            PostMedia.objects.create(
                post=post,
                media_type=media.get('media_type', 'image'),
                url=media.get('url', ''),
                thumbnail_url=media.get('thumbnail_url', ''),
                sort_order=media.get('sort_order', index),
                width=media.get('width') or None,
                height=media.get('height') or None,
                duration=media.get('duration') or None,
                file_size=media.get('file_size') or None,
            )

        for tid in set(topic_ids):
            PostTopic.objects.create(post=post, topic_id=tid)

        return Response(AdminPostDetailSerializer(post).data, status=201)

class AdminPostCategoryViewSet(ReadOnlyModelViewSet):
    """
    管理员端帖子分类
    用 ManagerAuthentication，避免管理员 token 请求用户端分类接口时报 Token 类型不匹配
    """
    queryset = PostCategory.objects.filter(is_active=True).order_by('sort_order', 'id')
    serializer_class = PostCategorySerializer
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
# ======================================================================
# 管理员 — 举报管理
# ======================================================================

class AdminReportViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    GenericViewSet,
):
    """
    举报管理（平台后台）
    handler FK 已指向 Manager，直接赋值 request.user
    """
    serializer_class = ReportAdminSerializer
    filterset_class = ReportFilter
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]

    def get_queryset(self):
        qs = Report.objects.select_related('reporter', 'handler').order_by('-created_at')
        return apply_filters(qs, self.request, self.filterset_class)

    def list(self, request, *args, **kwargs):
        paginated, paginator = paginate_queryset(self.get_queryset(), request, 'admin')
        serializer = self.get_serializer(paginated, many=True)
        return create_paginated_response(serializer.data, paginator)

    def perform_update(self, serializer):
        report = serializer.save()
        if report.status in ('resolved', 'rejected', 'ignored'):
            changed = []
            if not report.handler_id:
                report.handler = self.request.user
                changed.append('handler')
            if not report.handled_at:
                report.handled_at = timezone.now()
                changed.append('handled_at')
            if changed:
                report.save(update_fields=changed)

    def _finish(self, request, new_status):
        report = self.get_object()
        report.status = new_status
        report.handler = request.user
        report.handled_at = timezone.now()
        if 'handle_note' in request.data:
            report.handle_note = request.data['handle_note']
        report.save(update_fields=['status', 'handler', 'handled_at', 'handle_note'])
        return Response({'detail': '操作成功', 'status': new_status})

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        report = self.get_object()
        report.status = 'processing'
        report.handler = request.user
        report.save(update_fields=['status', 'handler'])
        return Response({'detail': '已标记为处理中', 'status': 'processing'})

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        return self._finish(request, 'resolved')

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        return self._finish(request, 'rejected')

    @action(detail=True, methods=['post'])
    def ignore(self, request, pk=None):
        return self._finish(request, 'ignored')

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        qs = Report.objects.all()
        status_counts = {
            r['status']: r['c'] for r in qs.values('status').annotate(c=Count('id'))
        }
        type_counts = {
            r['report_type']: r['c'] for r in qs.values('report_type').annotate(c=Count('id'))
        }
        return Response({
            'total': qs.count(),
            'pending': status_counts.get('pending', 0),
            'processing': status_counts.get('processing', 0),
            'resolved': status_counts.get('resolved', 0),
            'rejected': status_counts.get('rejected', 0),
            'ignored': status_counts.get('ignored', 0),
            'by_status': status_counts,
            'by_report_type': type_counts,
        })


# ======================================================================
# 宠物社区首页
# ======================================================================

class PetCommunityViewSet(ViewSet):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]

    def list(self, request):
        """首页聚合数据"""
        hot_topics = (
            Topic.objects.filter(status='approved')
            .order_by('-hot_score')[:5]
        )

        featured_posts = (
            Post.objects.filter(
                status='approved', is_featured=True,
                published_at__date=timezone.now().date(),
            )
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')[:3]
        )

        new_users = (
            User.objects.filter(
                is_active=True,
                date_joined__gte=timezone.now() - timedelta(days=7),
            )
            .annotate(pc=Count('posts', filter=Q(posts__status='approved')))
            .filter(pc__gte=1)[:5]
        )

        category_stats = (
            PostCategory.objects.filter(is_active=True)
            .annotate(ap=Count('posts', filter=Q(posts__status='approved')))
            .order_by('-ap')
        )

        return Response({
            'hot_topics': SimpleTopicSerializer(hot_topics, many=True).data,
            'featured_posts': PostListSerializer(
                featured_posts, many=True, context={'request': request}
            ).data,
            'new_users': BasicUserSerializer(new_users, many=True).data,
            'category_stats': PostCategorySerializer(category_stats, many=True).data,
        })

    @action(detail=False, methods=['get'])
    def home_posts(self, request):
        """首页帖子列表"""
        try:
            page = int(request.GET.get('page', 1))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.GET.get('page_size', 10))
        except (TypeError, ValueError):
            page_size = 10

        qs = (
            Post.objects.filter(status='approved')
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-is_featured', '-is_top', '-hot_score', '-published_at')
        )

        # 排除黑名单
        if isinstance(request.user, User) and request.user.is_authenticated:
            blocked = BlockedUser.objects.filter(
                user=request.user
            ).values_list('blocked_user', flat=True)
            if blocked:
                qs = qs.exclude(author__in=blocked)

        paginator = Paginator(qs, page_size)
        try:
            posts_page = paginator.page(page)
        except (EmptyPage, PageNotAnInteger):
            posts_page = paginator.page(1)

        serializer = PostListSerializer(
            posts_page.object_list, many=True, context={'request': request}
        )

        return Response({
            'success': True,
            'data': {
                'posts': serializer.data,
                'pagination': {
                    'current_page': posts_page.number,
                    'total_pages': paginator.num_pages,
                    'total_count': paginator.count,
                    'has_next': posts_page.has_next(),
                    'has_previous': posts_page.has_previous(),
                    'page_size': page_size,
                }
            }
        })

    @action(detail=False, methods=['get'])
    def pet_care_tips(self, request):
        posts = (
            Post.objects.filter(
                status='approved',
                category__name__in=['护理知识', '健康指南', '饲养技巧'],
                is_featured=True,
            )
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')[:10]
        )
        serializer = PostListSerializer(posts, many=True, context={'request': request})
        return Response({'tips': serializer.data})

    @action(detail=False, methods=['get'])
    def pet_adoption(self, request):
        posts = (
            Post.objects.filter(status='approved', category__name='领养信息')
            .select_related('author', 'category')
            .prefetch_related('medias', 'post_topics__topic')
            .order_by('-published_at')[:20]
        )
        serializer = PostListSerializer(posts, many=True, context={'request': request})
        return Response({'adoptions': serializer.data})


# ======================================================================
# 统计
# ======================================================================

class StatisticsView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request):
        today = timezone.now().date()
        return Response({
            'total_stats': {
                'users': User.objects.filter(is_active=True).count(),
                'posts': Post.objects.filter(status='approved').count(),
                'comments': Comment.objects.filter(is_deleted=False).count(),
                'topics': Topic.objects.filter(status='approved').count(),
            },
            'today_stats': {
                'posts': Post.objects.filter(published_at__date=today, status='approved').count(),
                'users': User.objects.filter(date_joined__date=today).count(),
            },
            'active_users': User.objects.filter(
                last_login__gte=timezone.now() - timedelta(days=7), is_active=True
            ).count(),
        })


# ======================================================================
# 实时数据
# ======================================================================

class RealtimeView(APIView):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def get(self, request):
        recent = Notification.objects.filter(
            receiver=request.user, is_read=False,
            created_at__gte=timezone.now() - timedelta(hours=24),
        ).order_by('-created_at')[:5]

        return Response({
            'notifications': NotificationSerializer(recent, many=True).data,
            'timestamp': timezone.now().isoformat(),
        })

# ======================================================================
# 创作者中心 — 内容数据（近 N 天互动表现，仅本人）
# ======================================================================
class ContentDataView(APIView):
    """
    创作者中心「内容数据」面板。
    返回窗口总数、累计总数，以及每日 trend，供前端绘制真实折线图。
    口径：近 N 个自然日，包含今天；days 限制 1~90。
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def get(self, request):
        user = request.user

        try:
            days = int(request.GET.get('days', 7))
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(days, 90))

        # 自然日口径：今天 + 前 days-1 天，和折线图 X 轴一致
        today = timezone.localdate()
        start_date = today - timedelta(days=days - 1)
        start_dt = timezone.localtime(timezone.now()).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days - 1)

        my_posts = Post.objects.filter(author=user)
        posts_count = my_posts.count()

        def daily_map(qs, field_name):
            return {
                row['day']: row['count']
                for row in qs.annotate(day=TruncDate(field_name))
                .values('day')
                .annotate(count=Count('id'))
                .order_by('day')
            }

        if posts_count == 0:
            views_map = likes_map = collects_map = comments_map = {}
            total = self._zero()
        else:
            # 注意：PostView 这里仍沿用你原本的 count() 口径：登录用户去重浏览记录数。
            # 如果希望重复浏览也计入趋势，可把 Count('id') 改成 Sum('view_count')。
            views_map = daily_map(
                PostView.objects.filter(
                    post__author=user,
                    post__is_deleted=False,
                    updated_at__gte=start_dt,
                ),
                'updated_at',
            )
            likes_map = daily_map(
                UserAction.objects.filter(
                    action_type='like_post',
                    post__author=user,
                    post__is_deleted=False,
                    created_at__gte=start_dt,
                ),
                'created_at',
            )
            collects_map = daily_map(
                PostCollection.objects.filter(
                    post__author=user,
                    post__is_deleted=False,
                    created_at__gte=start_dt,
                ),
                'created_at',
            )
            comments_map = daily_map(
                Comment.objects.filter(
                    post__author=user,
                    post__is_deleted=False,
                    created_at__gte=start_dt,
                ),
                'created_at',
            )

            agg = my_posts.aggregate(
                views=Sum('view_count'),
                likes=Sum('like_count'),
                collects=Sum('collect_count'),
                comments=Sum('comment_count'),
            )
            total = {k: (v or 0) for k, v in agg.items()}

        trend = []
        for i in range(days):
            day = start_date + timedelta(days=i)
            trend.append({
                'date': day.isoformat(),
                'label': day.strftime('%m/%d'),
                'views': views_map.get(day, 0),
                'likes': likes_map.get(day, 0),
                'collects': collects_map.get(day, 0),
                'comments': comments_map.get(day, 0),
            })

        window = {
            'views': sum(item['views'] for item in trend),
            'likes': sum(item['likes'] for item in trend),
            'collects': sum(item['collects'] for item in trend),
            'comments': sum(item['comments'] for item in trend),
        }

        return Response({
            'success': True,
            'data': {
                'days': days,
                'posts_count': posts_count,
                'window': window,
                'total': total,
                'trend': trend,
            },
        })

    @staticmethod
    def _zero():
        return {'views': 0, 'likes': 0, 'collects': 0, 'comments': 0}

# ======================================================================
# 恶意词 / 敏感词检测
# ======================================================================

def detect_sensitive_words(text, bump_hit_count=True):
    """
    在 text 中检测启用的敏感词，返回处置建议。

    返回 dict:
      passed        无命中 / 仅命中 sensitive 时为 True
      action        'reject'(含 banned) > 'review'(含 review) > 'pass'
      hit_count     命中词数量
      hits          [{word, word_type, category, severity}, ...]
      filtered_text 命中词用各自 replacement 替换后的文本（大小写不敏感）
      max_severity  命中词里的最高严重度

    说明：
    - 采用最朴素的子串包含匹配（中文天然适用；英文可能误伤词中词，如
      "ass" 命中 "class"，这是关键词过滤的通用局限，需要更精确可上分词）。
    - 词库量级有限时（几千内）直接全表遍历即可；词量很大时改成
      Aho-Corasick(pyahocorasick) 或预构建 Trie，并给词库加缓存。
    """
    words = list(
        SensitiveWord.objects.filter(is_active=True)
        .only('id', 'word', 'word_type', 'category', 'replacement', 'severity')
    )
    # 长词优先，保证替换更精确（先替 "习近平" 再替 "习"）
    words.sort(key=lambda w: len(w.word), reverse=True)

    lowered = text.lower()
    hits, hit_ids = [], []
    filtered = text

    for w in words:
        needle = (w.word or '').strip()
        if not needle or needle.lower() not in lowered:
            continue
        hits.append({
            'word': w.word,
            'word_type': w.word_type,
            'category': w.category,
            'severity': w.severity,
        })
        hit_ids.append(w.id)
        repl = w.replacement or '***'
        # 用 lambda 避免 replacement 里的 \1 等被当成反向引用
        filtered = re.sub(re.escape(needle), lambda m: repl, filtered, flags=re.IGNORECASE)

    # 命中计数 +1（原子；由运营看词命中分布，异步对账不要求顺序）
    if bump_hit_count and hit_ids:
        SensitiveWord.objects.filter(id__in=hit_ids).update(hit_count=F('hit_count') + 1)

    # 处置：用 word_type 决策（比按 severity 硬阈值更贴合模型语义）
    types = {h['word_type'] for h in hits}
    if 'banned' in types:
        action = 'reject'
    elif 'review' in types:
        action = 'review'
    else:
        action = 'pass'

    return {
        'passed': not hits,
        'action': action,
        'hit_count': len(hits),
        'hits': hits,
        'filtered_text': filtered,
        'max_severity': max((h['severity'] for h in hits), default=0),
    }


class SensitiveWordCheckView(APIView):
    """
    恶意词 / 敏感词检测（发帖 / 评论前预检）
    POST /api/v1/community/sensitive-check/
    body:
      text      待检测文本（必填）
      dry_run   true 时只检测、不累加 hit_count（前端实时预检可用），默认 false
    """
    authentication_classes = [UserAuthentication]
    permission_classes = [IsUser]

    def post(self, request):
        text = request.data.get('text', '')
        if not isinstance(text, str):
            return Response({'detail': 'text 必须是字符串'}, status=status.HTTP_400_BAD_REQUEST)
        text = text.strip()
        if not text:
            return Response({'detail': '请提供待检测文本'}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > 20000:
            return Response({'detail': '文本过长，最多 20000 字'}, status=status.HTTP_400_BAD_REQUEST)

        dry_run = str(request.data.get('dry_run', '')).lower() in ('1', 'true', 'yes')
        result = detect_sensitive_words(text, bump_hit_count=not dry_run)
        return Response({'success': True, 'data': result})

