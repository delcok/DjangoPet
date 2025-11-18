# -*- coding: utf-8 -*-
# @Time    : 2025/8/23 15:31
# @Author  : Delock

from rest_framework import serializers
from django.contrib.auth.models import User
from django.db import transaction
from .models import (
    PostCategory, Post, PostMedia, Comment, Topic, UserAction,
    Report, Notification,
    UserFollow, PostCollection, BlockedUser
)



# ===== 基础用户信息序列化 =====
class BasicUserSerializer(serializers.ModelSerializer):
    """基础用户信息（用于嵌套）"""
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'avatar']

    def get_avatar(self, obj):
        # 这里可以根据实际的用户头像字段调整
        return f"{obj.avatar}"


class UserDetailSerializer(serializers.ModelSerializer):
    """用户详细信息"""
    avatar = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    posts_count = serializers.SerializerMethodField()
    is_followed = serializers.SerializerMethodField()
    is_blocked = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name',
            'date_joined', 'avatar', 'followers_count', 'following_count',
            'posts_count', 'is_followed', 'is_blocked'
        ]
        read_only_fields = ['id', 'date_joined', 'email']

    def get_avatar(self, obj):
        return f"{obj.avatar}"

    def get_followers_count(self, obj):
        return obj.followers.count()

    def get_following_count(self, obj):
        return obj.following.count()

    def get_posts_count(self, obj):
        return obj.posts.filter(status='approved').count()

    def get_is_followed(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserFollow.objects.filter(
                follower=request.user, following=obj
            ).exists()
        return False

    def get_is_blocked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return BlockedUser.objects.filter(
                user=request.user, blocked_user=obj
            ).exists()
        return False


# ===== 分类相关序列化 =====
class PostCategorySerializer(serializers.ModelSerializer):
    """帖子分类"""

    class Meta:
        model = PostCategory
        fields = [
            'id', 'name', 'slug', 'icon', 'color', 'sort_order',
            'is_active', 'post_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'post_count', 'created_at', 'updated_at']


# ===== 媒体文件序列化 =====
class PostMediaSerializer(serializers.ModelSerializer):
    """帖子媒体文件"""

    class Meta:
        model = PostMedia
        fields = [
            'id', 'media_type', 'url', 'thumbnail_url', 'sort_order',
            'width', 'height', 'duration', 'file_size'
        ]
        read_only_fields = ['id']


# ===== 话题相关序列化 =====
class TopicSerializer(serializers.ModelSerializer):
    """话题"""
    creator = BasicUserSerializer(read_only=True)
    is_followed = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = [
            'id', 'name', 'slug', 'description', 'cover_image', 'creator',
            'is_official', 'is_trending', 'is_featured', 'status',
            'post_count', 'participant_count', 'follow_count', 'view_count',
            'hot_score', 'is_followed', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'slug', 'creator', 'post_count', 'participant_count',
            'follow_count', 'view_count', 'hot_score', 'created_at', 'updated_at'
        ]

    def get_is_followed(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserAction.objects.filter(
                user=request.user, topic=obj, action_type='follow_topic'
            ).exists()
        return False


class SimpleTopicSerializer(serializers.ModelSerializer):
    """简化的话题信息（用于嵌套）"""

    class Meta:
        model = Topic
        fields = ['id', 'name', 'slug', 'is_official', 'post_count']


# ===== 评论相关序列化 =====
class CommentSerializer(serializers.ModelSerializer):
    """评论"""
    author = BasicUserSerializer(read_only=True)
    replies = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id', 'author', 'parent', 'content', 'like_count', 'reply_count',
            'is_author_reply', 'is_featured', 'location', 'created_at',
            'replies', 'is_liked', 'can_delete'
        ]
        read_only_fields = [
            'id', 'author', 'like_count', 'reply_count', 'is_author_reply',
            'is_featured', 'created_at'
        ]

    def get_replies(self, obj):
        if obj.replies.exists():
            return CommentSerializer(
                obj.replies.filter(is_deleted=False)[:3],
                many=True,
                context=self.context
            ).data
        return []

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserAction.objects.filter(
                user=request.user, comment=obj, action_type='like_comment'
            ).exists()
        return False

    def get_can_delete(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.author == request.user or request.user.typ == 'admin'
        return False


class CreateCommentSerializer(serializers.ModelSerializer):
    """创建评论"""

    class Meta:
        model = Comment
        fields = ['post', 'parent', 'content']

    def validate(self, attrs):
        post = attrs.get('post')
        parent = attrs.get('parent')

        # 验证帖子状态
        if post.status != 'approved':
            raise serializers.ValidationError("无法对此帖子进行评论")

        # 验证父评论
        if parent and parent.post != post:
            raise serializers.ValidationError("父评论与帖子不匹配")

        return attrs

    def create(self, validated_data):
        validated_data['author'] = self.context['request'].user

        # 获取IP地址
        request = self.context['request']
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            validated_data['ip_address'] = x_forwarded_for.split(',')[0]
        else:
            validated_data['ip_address'] = request.META.get('REMOTE_ADDR')

        return super().create(validated_data)


# ===== 帖子相关序列化 =====
class PostListSerializer(serializers.ModelSerializer):
    """帖子列表"""
    author = BasicUserSerializer(read_only=True)
    category = PostCategorySerializer(read_only=True)
    cover_media = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    is_collected = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author', 'category', 'post_type', 'title', 'content',
            'cover_image', 'cover_media', 'location', 'view_count',
            'like_count', 'comment_count', 'collect_count', 'share_count',
            'hot_score', 'is_featured', 'is_top', 'published_at',
            'is_liked', 'is_collected', 'engagement_rate'
        ]

    def get_cover_media(self, obj):
        first_media = obj.medias.first()
        if first_media:
            return PostMediaSerializer(first_media).data
        return None

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserAction.objects.filter(
                user=request.user, post=obj, action_type='like_post'
            ).exists()
        return False

    def get_is_collected(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return PostCollection.objects.filter(
                user=request.user, post=obj
            ).exists()
        return False


class PostDetailSerializer(serializers.ModelSerializer):
    """帖子详情"""
    author = BasicUserSerializer(read_only=True)
    category = PostCategorySerializer(read_only=True)
    medias = PostMediaSerializer(many=True, read_only=True)
    recent_comments = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    is_collected = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id', 'author', 'category', 'post_type', 'title', 'content',
            'cover_image', 'medias', 'location', 'latitude', 'longitude',
            'view_count', 'like_count', 'comment_count', 'collect_count',
            'share_count', 'hot_score', 'quality_score', 'is_featured',
            'is_top', 'published_at', 'created_at', 'updated_at',
            'recent_comments', 'is_liked', 'is_collected', 'can_edit',
            'can_delete', 'engagement_rate'
        ]

    def get_recent_comments(self, obj):
        comments = obj.comments.filter(is_deleted=False, parent__isnull=True)[:5]
        return CommentSerializer(comments, many=True, context=self.context).data

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserAction.objects.filter(
                user=request.user, post=obj, action_type='like_post'
            ).exists()
        return False

    def get_is_collected(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return PostCollection.objects.filter(
                user=request.user, post=obj
            ).exists()
        return False

    def get_can_edit(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.author == request.user and obj.status in ['draft', 'pending']
        return False

    def get_can_delete(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.author == request.user
        return False


class CreatePostSerializer(serializers.ModelSerializer):
    """创建帖子"""
    medias = PostMediaSerializer(many=True, required=False)

    class Meta:
        model = Post
        fields = [
            'category', 'post_type', 'title', 'content', 'cover_image',
            'location', 'latitude', 'longitude', 'medias'
        ]

    def validate_title(self, value):
        if len(value.strip()) < 2:
            raise serializers.ValidationError("标题至少需要2个字符")
        return value.strip()

    def validate_content(self, value):
        if len(value.strip()) < 5:
            raise serializers.ValidationError("内容至少需要5个字符")
        return value.strip()

    @transaction.atomic
    def create(self, validated_data):
        medias_data = validated_data.pop('medias', [])
        validated_data['author'] = self.context['request'].user
        validated_data['status'] = 'pending'  # 默认待审核

        post = Post.objects.create(**validated_data)

        # 创建媒体文件
        for media_data in medias_data:
            PostMedia.objects.create(post=post, **media_data)

        return post


class UpdatePostSerializer(serializers.ModelSerializer):
    """更新帖子"""

    class Meta:
        model = Post
        fields = ['category', 'title', 'content', 'location', 'latitude', 'longitude']

    def validate(self, attrs):
        # 只有作者才能编辑，且只能编辑草稿和待审核状态
        if self.instance.status not in ['draft', 'pending']:
            raise serializers.ValidationError("当前状态下无法编辑")
        return attrs


# ===== 用户行为相关序列化 =====
class UserActionSerializer(serializers.ModelSerializer):
    """用户行为"""

    class Meta:
        model = UserAction
        fields = ['action_type', 'post', 'comment', 'target_user', 'topic']
        read_only_fields = ['user', 'created_at']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user

        # 获取IP地址
        request = self.context['request']
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            validated_data['ip_address'] = x_forwarded_for.split(',')[0]
        else:
            validated_data['ip_address'] = request.META.get('REMOTE_ADDR')

        validated_data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')

        return super().create(validated_data)


# ===== 收藏相关序列化 =====
class PostCollectionSerializer(serializers.ModelSerializer):
    """帖子收藏"""
    post = PostListSerializer(read_only=True)

    class Meta:
        model = PostCollection
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


# ===== 关注相关序列化 =====
class UserFollowSerializer(serializers.ModelSerializer):
    """用户关注关系序列化器"""
    user = serializers.SerializerMethodField()

    class Meta:
        model = UserFollow
        fields = ['id', 'user', 'is_mutual', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_user(self, obj):
        """根据context中的type返回对应的用户信息"""
        request = self.context.get('request')
        follow_type = self.context.get('type', 'following')

        if follow_type == 'following':
            # 显示被关注的用户
            user = obj.following
        else:
            # 显示关注者
            user = obj.follower

        # 返回用户详细信息
        data = {
            'id': user.id,
            'username': user.username,
            'avatar': f"{user.avatar}",
            'is_mutual': obj.is_mutual,
        }

        # 如果有请求上下文，添加当前用户是否关注该用户
        if request and request.user.is_authenticated:
            data['is_followed'] = UserFollow.objects.filter(
                follower=request.user,
                following=user
            ).exists()

        return data


# ===== 举报相关序列化 =====
class ReportSerializer(serializers.ModelSerializer):
    """举报"""
    reporter = BasicUserSerializer(read_only=True)
    handler = BasicUserSerializer(read_only=True)

    class Meta:
        model = Report
        fields = [
            'id', 'reporter', 'content_type', 'content_id', 'report_type',
            'reason', 'evidence', 'status', 'handler', 'handle_note',
            'created_at', 'handled_at'
        ]
        read_only_fields = [
            'id', 'reporter', 'status', 'handler', 'handle_note',
            'created_at', 'handled_at'
        ]

    def create(self, validated_data):
        validated_data['reporter'] = self.context['request'].user

        # 获取IP地址
        request = self.context['request']
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            validated_data['ip_address'] = x_forwarded_for.split(',')[0]
        else:
            validated_data['ip_address'] = request.META.get('REMOTE_ADDR')

        return super().create(validated_data)


# ===== 通知相关序列化 =====
class NotificationSerializer(serializers.ModelSerializer):
    """通知消息"""
    sender = BasicUserSerializer(read_only=True)
    post = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            'id', 'sender', 'notification_type', 'title', 'content',
            'post', 'extra_data', 'is_read', 'created_at', 'read_at'
        ]
        read_only_fields = ['id', 'sender', 'created_at', 'read_at']

    def get_post(self, obj):
        if obj.post:
            return {
                'id': obj.post.id,
                'title': obj.post.title,
                'cover_image': obj.post.cover_image
            }
        return None


# ===== 黑名单相关序列化 =====
class BlockedUserSerializer(serializers.ModelSerializer):
    """用户黑名单"""
    blocked_user = BasicUserSerializer(read_only=True)

    class Meta:
        model = BlockedUser
        fields = ['id', 'blocked_user', 'reason', 'created_at']
        read_only_fields = ['id', 'created_at']
