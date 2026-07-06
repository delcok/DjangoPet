# -*- coding: utf-8 -*-
"""
community/serializers.py
社区模块序列化器 — 用户端 + 管理员端
"""
import uuid

from django.utils.text import slugify
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone

from user.models import User
from managers.models import Manager
from .models import (
    PostCategory, Post, PostMedia, Comment, Topic, UserAction,
    Report, Notification, UserFollow, PostCollection, BlockedUser,
    PostTopic, Mention, PostView, SensitiveWord,
)


def _attach_post_flags(context, post_ids, user):
    """一次性算出当前用户点赞/收藏的帖子集合，存进 context（只算一次）。"""
    if user and post_ids and context.get('liked_post_ids') is None:
        context['liked_post_ids'] = set(
            UserAction.objects.filter(
                user=user, action_type='like_post', post_id__in=post_ids
            ).values_list('post_id', flat=True)
        )
        context['collected_post_ids'] = set(
            PostCollection.objects.filter(
                user=user, post_id__in=post_ids
            ).values_list('post_id', flat=True)
        )


class _PostFlagListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        items = list(data)
        user = _get_user(self.context)
        _attach_post_flags(self.context, [p.pk for p in items], user)
        return super().to_representation(items)


class _CollectionFlagListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        items = list(data)
        user = _get_user(self.context)
        _attach_post_flags(self.context, [c.post_id for c in items], user)
        return super().to_representation(items)

# ======================================================================
# 工具函数
# ======================================================================

def _get_user(context):
    """
    从序列化器 context 安全获取 User 实例。
    request.user 不是 User（如 Manager / AnonymousUser）时返回 None，
    避免把非 User 主体传进 UserAction / PostCollection 等 FK 查询导致类型报错。
    """
    request = context.get('request')
    if request and isinstance(getattr(request, 'user', None), User):
        return request.user
    return None


def _get_client_ip(request):
    """从 request 提取客户端 IP"""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')


# ======================================================================
# 基础用户 / 管理员 序列化器（用于嵌套）
# ======================================================================

class BasicUserSerializer(serializers.ModelSerializer):
    """用户基础信息（头像、昵称）"""
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'avatar']

    def get_avatar(self, obj):
        return str(obj.avatar) if obj.avatar else ''


class BasicManagerSerializer(serializers.ModelSerializer):
    """管理员基础信息（审核人 / 处理人嵌套用）"""
    class Meta:
        model = Manager
        fields = ['id', 'username', 'name']


class UserDetailSerializer(serializers.ModelSerializer):
    """用户详细信息（个人主页等场景）"""
    avatar = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    posts_count = serializers.SerializerMethodField()
    is_followed = serializers.SerializerMethodField()
    is_blocked = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'avatar',
            'followers_count', 'following_count', 'posts_count',
            'is_followed', 'is_blocked',
        ]
        read_only_fields = ['id', 'email']

    def get_avatar(self, obj):
        return str(obj.avatar) if obj.avatar else ''

    def get_followers_count(self, obj):
        return obj.followers.count()

    def get_following_count(self, obj):
        return obj.following.count()

    def get_posts_count(self, obj):
        return obj.posts.filter(status='approved', is_deleted=False).count()

    def get_is_followed(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return UserFollow.objects.filter(follower=user, following=obj).exists()

    def get_is_blocked(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return BlockedUser.objects.filter(user=user, blocked_user=obj).exists()


# ======================================================================
# 分类
# ======================================================================

class PostCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PostCategory
        fields = [
            'id', 'name', 'slug', 'icon', 'color', 'sort_order',
            'is_active', 'post_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'post_count', 'created_at', 'updated_at']


# ======================================================================
# 媒体
# ======================================================================

class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = [
            'id', 'media_type', 'url', 'thumbnail_url', 'sort_order',
            'width', 'height', 'duration', 'file_size',
        ]
        read_only_fields = ['id']


# ======================================================================
# 话题
# ======================================================================

class SimpleTopicSerializer(serializers.ModelSerializer):
    """简化话题（嵌套用）"""
    class Meta:
        model = Topic
        fields = ['id', 'name', 'slug', 'is_official', 'post_count']


class TopicSerializer(serializers.ModelSerializer):
    """话题完整信息"""
    creator = BasicUserSerializer(read_only=True)
    is_followed = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = [
            'id', 'name', 'slug', 'description', 'cover_image', 'creator',
            'is_official', 'is_trending', 'is_featured', 'status',
            'post_count', 'participant_count', 'follow_count', 'view_count',
            'hot_score', 'is_followed', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'slug', 'creator', 'post_count', 'participant_count',
            'follow_count', 'view_count', 'hot_score', 'created_at', 'updated_at',
        ]

    def get_is_followed(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return UserAction.objects.filter(
            user=user, topic=obj, action_type='follow_topic'
        ).exists()


class PostTopicSerializer(serializers.ModelSerializer):
    """帖子-话题关联（嵌套展示）"""
    topic = SimpleTopicSerializer(read_only=True)

    class Meta:
        model = PostTopic
        fields = ['id', 'topic', 'created_at']
        read_only_fields = ['id', 'created_at']


# ======================================================================
# 评论（用户端）
# ======================================================================
class _CommentFlagListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        items = list(data)
        user = _get_user(self.context)
        if user and items and self.context.get('liked_comment_ids') is None:
            ids = set()
            for c in items:
                ids.add(c.pk)
                for r in getattr(c, 'active_replies', None) or []:
                    ids.add(r.pk)
            self.context['liked_comment_ids'] = set(
                UserAction.objects.filter(
                    user=user, action_type='like_comment', comment_id__in=ids
                ).values_list('comment_id', flat=True)
            )
        return super().to_representation(items)

class CommentSerializer(serializers.ModelSerializer):
    """评论（用户端，含 is_liked / can_delete）"""
    author = BasicUserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        list_serializer_class = _CommentFlagListSerializer
        fields = [
            'id', 'author', 'parent', 'content',
            'like_count', 'reply_count',
            'is_author_reply', 'is_featured', 'is_edited', 'edited_at',
            'location', 'created_at',
            'replies', 'is_liked', 'can_delete',
        ]
        read_only_fields = [
            'id', 'author', 'like_count', 'reply_count',
            'is_author_reply', 'is_featured', 'is_edited', 'edited_at', 'created_at',
        ]

    def get_replies(self, obj):
        replies = getattr(obj, 'active_replies', None)
        if replies is None:  # 兜底（详情页 recent_comments 没预取时）
            replies = list(obj.replies.filter(is_deleted=False).order_by('-created_at')[:3])
        else:
            replies = replies[:3]
        if not replies:
            return []
        return CommentSerializer(replies, many=True, context=self.context).data

    def get_is_liked(self, obj):
        ids = self.context.get('liked_comment_ids')
        if ids is not None:
            return obj.pk in ids
        user = _get_user(self.context)
        if not user:
            return False
        return UserAction.objects.filter(
            user=user, comment=obj, action_type='like_comment'
        ).exists()

    def get_can_delete(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return obj.author_id == user.id


class CreateCommentSerializer(serializers.ModelSerializer):
    """创建评论"""
    class Meta:
        model = Comment
        fields = ['post', 'parent', 'content']

    def validate(self, attrs):
        post = attrs.get('post')
        parent = attrs.get('parent')

        if post.status != 'approved':
            raise serializers.ValidationError("无法对此帖子进行评论")
        if parent and parent.post_id != post.id:
            raise serializers.ValidationError("父评论与帖子不匹配")

        return attrs

    def create(self, validated_data):
        request = self.context['request']
        validated_data['author'] = request.user
        validated_data['ip_address'] = _get_client_ip(request)
        return super().create(validated_data)


# ======================================================================
# 帖子（用户端）
# ======================================================================

class PostListSerializer(serializers.ModelSerializer):
    """帖子列表（用户端）"""
    author = BasicUserSerializer(read_only=True)
    category = PostCategorySerializer(read_only=True)
    cover_media = serializers.SerializerMethodField()
    topics = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    is_collected = serializers.SerializerMethodField()

    class Meta:
        model = Post
        list_serializer_class = _PostFlagListSerializer
        fields = [
            'id', 'author', 'category', 'post_type', 'status',
            'title', 'content', 'cover_image', 'cover_media', 'topics',
            'location', 'view_count', 'like_count', 'comment_count',
            'collect_count', 'share_count', 'hot_score',
            'is_featured', 'is_top', 'published_at',
            'is_liked', 'is_collected', 'engagement_rate',
        ]

    def get_cover_media(self, obj):
        medias = list(obj.medias.all())  # 命中 prefetch 缓存，按 sort_order 排序
        return PostMediaSerializer(medias[0]).data if medias else None

    def get_topics(self, obj):
        # 依赖视图 prefetch_related('post_topics__topic')
        return SimpleTopicSerializer(
            [pt.topic for pt in obj.post_topics.all()], many=True
        ).data

    def get_is_liked(self, obj):
        ids = self.context.get('liked_post_ids')
        if ids is not None:
            return obj.pk in ids
        user = _get_user(self.context)  # 单对象/详情场景的兜底
        if not user:
            return False
        return UserAction.objects.filter(
            user=user, post=obj, action_type='like_post'
        ).exists()

    def get_is_collected(self, obj):
        ids = self.context.get('collected_post_ids')
        if ids is not None:
            return obj.pk in ids
        user = _get_user(self.context)
        if not user:
            return False
        return PostCollection.objects.filter(user=user, post=obj).exists()


class PostDetailSerializer(serializers.ModelSerializer):
    """帖子详情（用户端）"""
    author = BasicUserSerializer(read_only=True)
    category = PostCategorySerializer(read_only=True)
    medias = PostMediaSerializer(many=True, read_only=True)
    topics = serializers.SerializerMethodField()
    recent_comments = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    is_collected = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author', 'category', 'post_type', 'title', 'content',
            'cover_image', 'medias', 'topics',
            'location', 'latitude', 'longitude',
            'view_count', 'like_count', 'comment_count',
            'collect_count', 'share_count',
            'hot_score', 'quality_score',
            'is_featured', 'is_top', 'is_edited', 'edited_at',
            'published_at', 'created_at', 'updated_at',
            'recent_comments',
            'is_liked', 'is_collected', 'is_following',
            'is_mine', 'can_edit', 'can_delete',
            'engagement_rate', 'status',
        ]

    def get_topics(self, obj):
        return SimpleTopicSerializer(
            [pt.topic for pt in obj.post_topics.all()], many=True
        ).data

    def get_recent_comments(self, obj):
        qs = obj.comments.filter(is_deleted=False, parent__isnull=True)[:5]
        return CommentSerializer(qs, many=True, context=self.context).data

    def get_is_liked(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return UserAction.objects.filter(
            user=user, post=obj, action_type='like_post'
        ).exists()

    def get_is_collected(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return PostCollection.objects.filter(user=user, post=obj).exists()

    def get_is_following(self, obj):
        """当前用户是否关注了帖子作者"""
        user = _get_user(self.context)
        if not user or obj.author_id == user.id:
            return False
        return UserFollow.objects.filter(follower=user, following=obj.author).exists()

    def get_is_mine(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return obj.author_id == user.id

    def get_can_edit(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return obj.author_id == user.id and obj.status in ('draft', 'pending')

    def get_can_delete(self, obj):
        user = _get_user(self.context)
        if not user:
            return False
        return obj.author_id == user.id


class CreatePostSerializer(serializers.ModelSerializer):
    """创建帖子"""
    medias = PostMediaSerializer(many=True, required=False)
    topic_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )

    class Meta:
        model = Post
        fields = [
            'category', 'post_type', 'title', 'content', 'cover_image',
            'location', 'latitude', 'longitude', 'medias', 'topic_ids',
        ]

    def validate_title(self, value):
        value = value.strip()
        if len(value) < 2:
            raise serializers.ValidationError("标题至少需要2个字符")
        return value

    def validate_content(self, value):
        value = value.strip()
        if len(value) < 5:
            raise serializers.ValidationError("内容至少需要5个字符")
        return value

    def validate_topic_ids(self, value):
        if not value:
            return value
        valid_ids = set(
            Topic.objects.filter(id__in=value)
            .exclude(status__in=['banned', 'rejected', 'suspended'])
            .values_list('id', flat=True)
        )
        invalid = [tid for tid in value if tid not in valid_ids]
        if invalid:
            raise serializers.ValidationError(f"话题不存在或不可用: {invalid}")
        return value

    @transaction.atomic
    def create(self, validated_data):
        medias_data = validated_data.pop('medias', [])
        topic_ids = validated_data.pop('topic_ids', [])
        validated_data['author'] = self.context['request'].user
        validated_data['status'] = 'pending'

        post = Post.objects.create(**validated_data)

        for media_data in medias_data:
            PostMedia.objects.create(post=post, **media_data)

        for tid in set(topic_ids):
            PostTopic.objects.create(post=post, topic_id=tid)

        return post


class UpdatePostSerializer(serializers.ModelSerializer):
    """更新帖子"""
    class Meta:
        model = Post
        fields = ['category', 'title', 'content', 'location', 'latitude', 'longitude']

    def validate(self, attrs):
        if self.instance.status not in ('draft', 'pending'):
            raise serializers.ValidationError("当前状态下无法编辑")
        return attrs

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        instance.is_edited = True
        instance.edited_at = timezone.now()
        instance.save(update_fields=['is_edited', 'edited_at', 'updated_at'])
        return instance


# ======================================================================
# 帖子（管理员端）— 不查 request.user 的 UserAction / PostCollection
# ======================================================================

class AdminCommentSerializer(serializers.ModelSerializer):
    """管理员评论（不含 is_liked / can_delete）"""
    author = BasicUserSerializer(read_only=True)

    class Meta:
        model = Comment
        fields = [
            'id', 'author', 'parent', 'content',
            'like_count', 'reply_count',
            'is_author_reply', 'is_featured', 'is_deleted',
            'is_edited', 'edited_at', 'ip_address', 'location', 'created_at',
        ]


class AdminPostListSerializer(serializers.ModelSerializer):
    """管理员帖子列表"""
    author = BasicUserSerializer(read_only=True)
    category = PostCategorySerializer(read_only=True)
    reviewer = BasicManagerSerializer(read_only=True)
    cover_media = serializers.SerializerMethodField()
    topics = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author', 'category', 'post_type', 'status',
            'title', 'content', 'cover_image', 'cover_media', 'topics',
            'location',
            # 互动统计
            'view_count', 'like_count', 'comment_count',
            'collect_count', 'share_count',
            # 分数
            'hot_score', 'quality_score', 'auto_review_score', 'review_priority',
            # 标记
            'is_featured', 'is_top', 'is_deleted', 'is_edited',
            # 违规 & 举报
            'violation_type', 'violation_count', 'report_count',
            # 审核
            'reviewer', 'reject_reason', 'reviewed_at',
            # 时间
            'published_at', 'created_at', 'updated_at',
        ]

    def get_cover_media(self, obj):
        first = obj.medias.first()
        return PostMediaSerializer(first).data if first else None

    def get_topics(self, obj):
        return SimpleTopicSerializer(
            [pt.topic for pt in obj.post_topics.all()], many=True
        ).data


class AdminPostDetailSerializer(AdminPostListSerializer):
    """管理员帖子详情（继承列表，补充完整字段）"""
    medias = PostMediaSerializer(many=True, read_only=True)
    recent_comments = serializers.SerializerMethodField()

    class Meta(AdminPostListSerializer.Meta):
        fields = AdminPostListSerializer.Meta.fields + [
            'medias', 'latitude', 'longitude',
            'review_note',
            'edited_at', 'deleted_at', 'last_active_at',
            'recent_comments', 'engagement_rate',
        ]

    def get_recent_comments(self, obj):
        qs = obj.comments.filter(is_deleted=False, parent__isnull=True)[:5]
        return AdminCommentSerializer(qs, many=True).data


# ======================================================================
# 用户行为
# ======================================================================

class UserActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAction
        fields = ['action_type', 'post', 'comment', 'target_user', 'topic']
        read_only_fields = ['user', 'created_at']

    def create(self, validated_data):
        request = self.context['request']
        validated_data['user'] = request.user
        validated_data['ip_address'] = _get_client_ip(request)
        validated_data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')
        return super().create(validated_data)


# ======================================================================
# 收藏
# ======================================================================

class PostCollectionSerializer(serializers.ModelSerializer):
    """收藏列表（含帖子摘要）"""
    post = PostListSerializer(read_only=True)

    class Meta:
        model = PostCollection
        list_serializer_class = _CollectionFlagListSerializer   # ← 新增：批量预取点赞/收藏标记，修掉 N+1
        fields = ['id', 'post', 'folder', 'note', 'created_at']
        read_only_fields = ['id', 'created_at']



class CreateCollectionSerializer(serializers.ModelSerializer):
    """创建收藏"""
    class Meta:
        model = PostCollection
        fields = ['post', 'folder', 'note']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

# ======================================================================
# 浏览历史
# ======================================================================

class PostViewHistorySerializer(serializers.ModelSerializer):
    """
    浏览历史（含帖子摘要）。
    PostView 和 PostCollection 一样都有 .post_id，直接复用
    _CollectionFlagListSerializer 按 post_id 批量预取当前用户的点赞/收藏标记，
    避免逐条 PostView 再去查 UserAction / PostCollection（N+1）。
    """
    post = PostListSerializer(read_only=True)

    class Meta:
        model = PostView
        list_serializer_class = _CollectionFlagListSerializer
        fields = ['id', 'post', 'view_count', 'duration', 'source', 'created_at', 'updated_at']
        read_only_fields = fields

# ======================================================================
# 关注
# ======================================================================

class UserFollowSerializer(serializers.ModelSerializer):
    """关注 / 粉丝关系"""
    user = serializers.SerializerMethodField()

    class Meta:
        model = UserFollow
        fields = ['id', 'user', 'is_mutual', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_user(self, obj):
        """根据 context['type'] 返回关注者或被关注者"""
        follow_type = self.context.get('type', 'following')
        target = obj.following if follow_type == 'following' else obj.follower

        data = {
            'id': target.id,
            'username': target.username,
            'avatar': str(target.avatar) if target.avatar else '',
            'is_mutual': obj.is_mutual,
        }

        user = _get_user(self.context)
        if user:
            data['is_followed'] = UserFollow.objects.filter(
                follower=user, following=target
            ).exists()

        return data


# ======================================================================
# 举报（用户端）
# ======================================================================

class ReportSerializer(serializers.ModelSerializer):
    """举报（用户提交 + 查看自己的举报）"""
    reporter = BasicUserSerializer(read_only=True)
    handler = BasicManagerSerializer(read_only=True)

    class Meta:
        model = Report
        fields = [
            'id', 'reporter', 'content_type', 'content_id', 'report_type',
            'reason', 'evidence', 'status',
            'handler', 'handle_note', 'created_at', 'handled_at',
        ]
        read_only_fields = [
            'id', 'reporter', 'status', 'handler', 'handle_note',
            'created_at', 'handled_at',
        ]

    def create(self, validated_data):
        request = self.context['request']
        validated_data['reporter'] = request.user
        validated_data['ip_address'] = _get_client_ip(request)
        return super().create(validated_data)


# ======================================================================
# 举报（管理员端）
# ======================================================================

class ReportAdminSerializer(serializers.ModelSerializer):
    """
    举报管理（平台后台）
    handler 指向 Manager，可直接赋值 request.user。
    reporter 指向 User，只读展示。
    """
    reporter = BasicUserSerializer(read_only=True)
    handler = BasicManagerSerializer(read_only=True)
    report_type_display = serializers.CharField(source='get_report_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    content_type_display = serializers.CharField(source='get_content_type_display', read_only=True)

    class Meta:
        model = Report
        fields = [
            'id', 'reporter',
            'content_type', 'content_type_display', 'content_id',
            'report_type', 'report_type_display',
            'reason', 'evidence',
            'status', 'status_display',
            'handler', 'handle_note',
            'ip_address', 'created_at', 'handled_at',
        ]
        read_only_fields = [
            'id', 'reporter', 'content_type', 'content_id', 'report_type',
            'reason', 'evidence', 'handler',
            'ip_address', 'created_at', 'handled_at',
        ]


# ======================================================================
# 通知
# ======================================================================

class NotificationSerializer(serializers.ModelSerializer):
    sender = BasicUserSerializer(read_only=True)
    post = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'sender', 'notification_type', 'title', 'content',
            'post', 'extra_data', 'is_read', 'created_at', 'read_at',
        ]
        read_only_fields = ['id', 'sender', 'created_at', 'read_at']

    def get_post(self, obj):
        if not obj.post:
            return None
        return {
            'id': obj.post.id,
            'title': obj.post.title,
            'cover_image': obj.post.cover_image,
        }


# ======================================================================
# 提及
# ======================================================================

class MentionSerializer(serializers.ModelSerializer):
    mention_by = BasicUserSerializer(read_only=True)
    mentioned_user = BasicUserSerializer(read_only=True)

    class Meta:
        model = Mention
        fields = [
            'id', 'mentioned_user', 'mention_by',
            'source_type', 'source_id', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ======================================================================
# 黑名单
# ======================================================================

class BlockedUserSerializer(serializers.ModelSerializer):
    blocked_user = BasicUserSerializer(read_only=True)

    class Meta:
        model = BlockedUser
        fields = ['id', 'blocked_user', 'reason', 'created_at']
        read_only_fields = ['id', 'created_at']


class AdminCreatePostSerializer(serializers.ModelSerializer):
    """管理员后台创建帖子：作者固定为 User(id=2)，也允许显式传 author_id 覆盖。"""
    author_id = serializers.IntegerField(required=False, write_only=True, default=2)
    medias = PostMediaSerializer(many=True, required=False)
    topic_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )
    topic_names = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, write_only=True
    )

    class Meta:
        model = Post
        fields = [
            'author_id', 'category', 'post_type', 'status',
            'title', 'content', 'cover_image', 'location', 'latitude', 'longitude',
            'is_featured', 'is_top', 'quality_score', 'review_priority', 'review_note',
            'medias', 'topic_ids', 'topic_names',
        ]

    def validate_title(self, value):
        value = (value or '').strip()
        if len(value) < 2:
            raise serializers.ValidationError('标题至少需要2个字符')
        if len(value) > 100:
            raise serializers.ValidationError('标题不能超过100个字符')
        return value

    def validate_content(self, value):
        value = (value or '').strip()
        if len(value) < 5:
            raise serializers.ValidationError('内容至少需要5个字符')
        return value

    def validate_author_id(self, value):
        value = value or 2
        if not User.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError(f'作者用户不存在或不可用: {value}')
        return value

    def validate_topic_ids(self, value):
        if not value:
            return []
        valid_ids = set(
            Topic.objects.filter(id__in=value)
            .exclude(status__in=['banned', 'rejected', 'suspended'])
            .values_list('id', flat=True)
        )
        invalid = [tid for tid in value if tid not in valid_ids]
        if invalid:
            raise serializers.ValidationError(f'话题不存在或不可用: {invalid}')
        return value

    @transaction.atomic
    def create(self, validated_data):
        author_id = validated_data.pop('author_id', 2) or 2
        medias_data = validated_data.pop('medias', [])
        topic_ids = validated_data.pop('topic_ids', [])
        topic_names = validated_data.pop('topic_names', [])

        author = User.objects.get(id=author_id, is_active=True)
        post = Post.objects.create(author=author, **validated_data)

        for index, media_data in enumerate(medias_data):
            media_data.setdefault('media_type', 'image')
            media_data.setdefault('sort_order', index)
            PostMedia.objects.create(post=post, **media_data)

        for tid in set(topic_ids):
            PostTopic.objects.get_or_create(post=post, topic_id=tid)

        for raw_name in topic_names:
            name = (raw_name or '').strip().lstrip('#').strip()
            if not name:
                continue
            topic = Topic.objects.filter(name=name).exclude(status__in=['banned', 'rejected', 'suspended']).first()
            if not topic:
                base = slugify(name, allow_unicode=True)[:40] or f'topic-{uuid.uuid4().hex[:8]}'
                slug = base
                i = 1
                while Topic.all_objects.filter(slug=slug).exists():
                    i += 1
                    slug = f'{base}-{i}'[:50]
                topic = Topic.objects.create(name=name, slug=slug, status='approved', is_official=True)
            PostTopic.objects.get_or_create(post=post, topic=topic)

        return post