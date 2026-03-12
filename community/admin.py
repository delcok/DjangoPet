# -*- coding: utf-8 -*-
from django.contrib import admin
from .models import (
    Post, PostCategory, PostMedia, Comment, Topic,
    UserAction, Report, Notification, PostView,
    UserFollow, PostCollection, BlockedUser,
    ReviewLog, SensitiveWord
)


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    """帖子管理"""
    list_display = [
        'id', 'title', 'author', 'category', 'post_type',
        'status', 'is_featured', 'is_top',
        'view_count', 'like_count', 'comment_count', 'collect_count',
        'hot_score', 'published_at', 'created_at'
    ]
    list_filter = ['status', 'is_featured', 'is_top', 'post_type', 'category']
    list_editable = ['status', 'is_featured', 'is_top']
    search_fields = ['title', 'content', 'author__username', 'author__phone']
    raw_id_fields = ['author', 'reviewer']
    readonly_fields = [
        'view_count', 'like_count', 'comment_count', 'collect_count',
        'share_count', 'hot_score', 'report_count', 'violation_count',
        'published_at', 'reviewed_at', 'created_at', 'updated_at'
    ]
    list_per_page = 20
    ordering = ['-created_at']

    fieldsets = (
        ('基本信息', {
            'fields': ('author', 'category', 'post_type', 'title', 'content', 'cover_image')
        }),
        ('位置信息', {
            'fields': ('location', 'latitude', 'longitude'),
            'classes': ('collapse',)
        }),
        ('互动统计', {
            'fields': (
                'view_count', 'like_count', 'comment_count',
                'collect_count', 'share_count'
            ),
        }),
        ('推荐权重', {
            'fields': ('hot_score', 'quality_score', 'is_featured', 'is_top'),
        }),
        ('审核管理', {
            'fields': (
                'status', 'reviewer', 'review_note', 'reject_reason',
                'reviewed_at', 'auto_review_score', 'review_priority'
            ),
        }),
        ('违规信息', {
            'fields': ('violation_type', 'violation_count', 'report_count'),
            'classes': ('collapse',)
        }),
        ('时间信息', {
            'fields': ('published_at', 'last_active_at', 'created_at', 'updated_at'),
        }),
    )

    actions = ['approve_posts', 'reject_posts', 'set_featured', 'unset_featured', 'set_top', 'unset_top']

    # ===== 批量操作（逐个save触发积分逻辑） =====

    @admin.action(description='✅ 审核通过选中帖子（作者+50积分）')
    def approve_posts(self, request, queryset):
        count = 0
        for post in queryset:
            if post.status != 'approved':
                post.status = 'approved'
                post.save()  # 触发 Post.save() 中的积分逻辑
                count += 1
        self.message_user(request, f'成功审核通过 {count} 篇帖子，每位作者+50积分')

    @admin.action(description='❌ 拒绝选中帖子')
    def reject_posts(self, request, queryset):
        count = 0
        for post in queryset:
            if post.status != 'rejected':
                post.status = 'rejected'
                post.save()
                count += 1
        self.message_user(request, f'已拒绝 {count} 篇帖子')

    @admin.action(description='⭐ 设为精选（作者+50积分）')
    def set_featured(self, request, queryset):
        count = 0
        for post in queryset:
            if not post.is_featured:
                post.is_featured = True
                post.save()  # 触发 Post.save() 中的积分逻辑
                count += 1
        self.message_user(request, f'成功设置 {count} 篇精选帖子，每位作者+50积分')

    @admin.action(description='取消精选')
    def unset_featured(self, request, queryset):
        count = queryset.count()
        # 取消精选不涉及积分，可以直接update
        queryset.update(is_featured=False)
        self.message_user(request, f'已取消 {count} 篇精选')

    @admin.action(description='📌 设为置顶')
    def set_top(self, request, queryset):
        queryset.update(is_top=True)
        self.message_user(request, f'已置顶 {queryset.count()} 篇帖子')

    @admin.action(description='取消置顶')
    def unset_top(self, request, queryset):
        queryset.update(is_top=False)
        self.message_user(request, f'已取消置顶 {queryset.count()} 篇帖子')


@admin.register(PostCategory)
class PostCategoryAdmin(admin.ModelAdmin):
    """帖子分类管理"""
    list_display = ['id', 'name', 'slug', 'icon', 'color', 'sort_order', 'is_active', 'post_count']
    list_editable = ['sort_order', 'is_active']
    search_fields = ['name', 'slug']
    list_filter = ['is_active']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['sort_order', 'id']


@admin.register(PostMedia)
class PostMediaAdmin(admin.ModelAdmin):
    """帖子媒体管理"""
    list_display = ['id', 'post', 'media_type', 'sort_order', 'width', 'height', 'file_size']
    list_filter = ['media_type']
    raw_id_fields = ['post']
    ordering = ['post', 'sort_order']


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """评论管理"""
    list_display = [
        'id', 'author', 'post', 'short_content',
        'like_count', 'reply_count', 'is_featured',
        'is_deleted', 'created_at'
    ]
    list_filter = ['is_deleted', 'is_featured', 'is_author_reply']
    search_fields = ['content', 'author__username']
    raw_id_fields = ['author', 'post', 'parent']
    list_editable = ['is_featured', 'is_deleted']
    ordering = ['-created_at']

    @admin.display(description='评论内容')
    def short_content(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    """话题管理"""
    list_display = [
        'id', 'name', 'slug', 'status', 'is_official',
        'is_trending', 'is_featured', 'post_count',
        'follow_count', 'hot_score', 'created_at'
    ]
    list_filter = ['status', 'is_official', 'is_trending', 'is_featured']
    list_editable = ['status', 'is_official', 'is_trending', 'is_featured']
    search_fields = ['name', 'description']
    raw_id_fields = ['creator', 'reviewer']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['-hot_score']


@admin.register(UserAction)
class UserActionAdmin(admin.ModelAdmin):
    """用户行为管理"""
    list_display = ['id', 'user', 'action_type', 'post', 'comment', 'target_user', 'topic', 'created_at']
    list_filter = ['action_type']
    search_fields = ['user__username']
    raw_id_fields = ['user', 'post', 'comment', 'target_user', 'topic']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """举报管理"""
    list_display = [
        'id', 'reporter', 'content_type', 'content_id',
        'report_type', 'status', 'handler', 'created_at', 'handled_at'
    ]
    list_filter = ['status', 'report_type', 'content_type']
    list_editable = ['status']
    search_fields = ['reporter__username', 'reason']
    raw_id_fields = ['reporter', 'handler']
    readonly_fields = ['created_at']
    ordering = ['-created_at']

    actions = ['mark_resolved', 'mark_rejected']

    @admin.action(description='标记为已处理')
    def mark_resolved(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='resolved', handled_at=timezone.now())
        self.message_user(request, f'已处理 {queryset.count()} 条举报')

    @admin.action(description='标记为已驳回')
    def mark_rejected(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='rejected', handled_at=timezone.now())
        self.message_user(request, f'已驳回 {queryset.count()} 条举报')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """通知管理"""
    list_display = ['id', 'receiver', 'sender', 'notification_type', 'title', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read']
    search_fields = ['receiver__username', 'title', 'content']
    raw_id_fields = ['receiver', 'sender', 'post', 'comment']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(PostView)
class PostViewAdmin(admin.ModelAdmin):
    """帖子浏览记录管理"""
    list_display = ['id', 'user', 'post', 'view_count', 'duration', 'source', 'created_at']
    search_fields = ['user__username']
    raw_id_fields = ['user', 'post']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(UserFollow)
class UserFollowAdmin(admin.ModelAdmin):
    """用户关注管理"""
    list_display = ['id', 'follower', 'following', 'is_mutual', 'created_at']
    list_filter = ['is_mutual']
    search_fields = ['follower__username', 'following__username']
    raw_id_fields = ['follower', 'following']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(PostCollection)
class PostCollectionAdmin(admin.ModelAdmin):
    """帖子收藏管理"""
    list_display = ['id', 'user', 'post', 'folder', 'created_at']
    search_fields = ['user__username', 'post__title']
    raw_id_fields = ['user', 'post']
    list_filter = ['folder']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(BlockedUser)
class BlockedUserAdmin(admin.ModelAdmin):
    """用户黑名单管理"""
    list_display = ['id', 'user', 'blocked_user', 'reason', 'created_at']
    search_fields = ['user__username', 'blocked_user__username']
    raw_id_fields = ['user', 'blocked_user']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(ReviewLog)
class ReviewLogAdmin(admin.ModelAdmin):
    """审核日志管理"""
    list_display = ['id', 'content_type', 'content_id', 'reviewer', 'action', 'old_status', 'new_status', 'created_at']
    list_filter = ['content_type', 'action']
    search_fields = ['reviewer__username', 'reason', 'note']
    raw_id_fields = ['reviewer']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(SensitiveWord)
class SensitiveWordAdmin(admin.ModelAdmin):
    """敏感词管理"""
    list_display = ['id', 'word', 'word_type', 'category', 'severity', 'is_active', 'hit_count']
    list_filter = ['word_type', 'category', 'is_active']
    list_editable = ['word_type', 'is_active', 'severity']
    search_fields = ['word']
    ordering = ['-severity', '-hit_count']