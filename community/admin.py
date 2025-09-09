# admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db.models import Count, Q
from django.utils import timezone
from .models import (
    PostCategory, Post, PostMedia, Comment, Topic, UserAction,
    ReviewLog, SensitiveWord, Report, Notification, PostView,
    UserFollow, PostCollection, BlockedUser
)


@admin.register(PostCategory)
class PostCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'colored_icon', 'post_count', 'sort_order', 'is_active', 'created_at']
    list_editable = ['sort_order', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['sort_order', 'name']

    def colored_icon(self, obj):
        if obj.icon:
            return format_html(
                '<span style="color: {}; font-size: 16px;">{}</span>',
                obj.color,
                obj.icon
            )
        return '-'

    colored_icon.short_description = '图标'

    actions = ['make_active', 'make_inactive']

    def make_active(self, request, queryset):
        queryset.update(is_active=True)

    make_active.short_description = "启用选中的分类"

    def make_inactive(self, request, queryset):
        queryset.update(is_active=False)

    make_inactive.short_description = "禁用选中的分类"


class PostMediaInline(admin.TabularInline):
    model = PostMedia
    extra = 0
    fields = ['media_type', 'url', 'thumbnail_url', 'sort_order', 'width', 'height']
    readonly_fields = ['width', 'height']


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'author', 'category', 'post_type', 'status',
        'interaction_stats', 'is_featured', 'is_top', 'published_at'
    ]
    list_filter = [
        'status', 'post_type', 'category', 'is_featured', 'is_top',
        'created_at', 'published_at'
    ]
    search_fields = ['title', 'content', 'author__username', 'author__email']
    readonly_fields = [
        'view_count', 'like_count', 'comment_count', 'collect_count',
        'share_count', 'hot_score', 'engagement_rate', 'created_at', 'updated_at'
    ]

    fieldsets = (
        ('基本信息', {
            'fields': ('author', 'category', 'post_type', 'title', 'content')
        }),
        ('媒体内容', {
            'fields': ('cover_image',)
        }),
        ('位置信息', {
            'fields': ('location', 'latitude', 'longitude'),
            'classes': ('collapse',)
        }),
        ('互动统计', {
            'fields': (
                'view_count', 'like_count', 'comment_count',
                'collect_count', 'share_count', 'engagement_rate'
            ),
            'classes': ('collapse',)
        }),
        ('推荐权重', {
            'fields': ('hot_score', 'quality_score'),
            'classes': ('collapse',)
        }),
        ('管理设置', {
            'fields': ('status', 'is_featured', 'is_top')
        }),
        ('审核信息', {
            'fields': (
                'reviewer', 'review_note', 'reject_reason', 'reviewed_at',
                'auto_review_score', 'review_priority'
            ),
            'classes': ('collapse',)
        }),
        ('违规处理', {
            'fields': ('violation_type', 'violation_count', 'report_count'),
            'classes': ('collapse',)
        }),
        ('时间记录', {
            'fields': ('created_at', 'updated_at', 'published_at', 'last_active_at'),
            'classes': ('collapse',)
        })
    )

    inlines = [PostMediaInline]

    actions = ['approve_posts', 'reject_posts', 'feature_posts', 'unfeature_posts', 'pin_posts', 'unpin_posts']

    def interaction_stats(self, obj):
        return format_html(
            '👁️ {} | ❤️ {} | 💬 {} | ⭐ {}',
            obj.view_count, obj.like_count, obj.comment_count, obj.collect_count
        )

    interaction_stats.short_description = '互动数据'

    def approve_posts(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='approved',
            published_at=timezone.now(),
            reviewer=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'成功通过 {count} 个帖子的审核')

    approve_posts.short_description = "通过审核"

    def reject_posts(self, request, queryset):
        count = queryset.filter(status__in=['pending', 'reviewing']).update(
            status='rejected',
            reviewer=request.user,
            reviewed_at=timezone.now()
        )
        self.message_user(request, f'成功拒绝 {count} 个帖子')

    reject_posts.short_description = "拒绝审核"

    def feature_posts(self, request, queryset):
        count = queryset.update(is_featured=True)
        self.message_user(request, f'成功精选 {count} 个帖子')

    feature_posts.short_description = "设为精选"

    def unfeature_posts(self, request, queryset):
        count = queryset.update(is_featured=False)
        self.message_user(request, f'成功取消精选 {count} 个帖子')

    unfeature_posts.short_description = "取消精选"

    def pin_posts(self, request, queryset):
        count = queryset.update(is_top=True)
        self.message_user(request, f'成功置顶 {count} 个帖子')

    pin_posts.short_description = "置顶"

    def unpin_posts(self, request, queryset):
        count = queryset.update(is_top=False)
        self.message_user(request, f'成功取消置顶 {count} 个帖子')

    unpin_posts.short_description = "取消置顶"


@admin.register(PostMedia)
class PostMediaAdmin(admin.ModelAdmin):
    list_display = ['post', 'media_type', 'thumbnail_preview', 'sort_order', 'file_info', 'created_at']
    list_filter = ['media_type', 'created_at']
    search_fields = ['post__title', 'post__author__username']
    readonly_fields = ['thumbnail_preview', 'file_info']

    def thumbnail_preview(self, obj):
        if obj.thumbnail_url:
            return format_html('<img src="{}" style="max-width: 100px; max-height: 100px;">', obj.thumbnail_url)
        elif obj.media_type == 'image' and obj.url:
            return format_html('<img src="{}" style="max-width: 100px; max-height: 100px;">', obj.url)
        return '-'

    thumbnail_preview.short_description = '预览'

    def file_info(self, obj):
        info = []
        if obj.width and obj.height:
            info.append(f'{obj.width}×{obj.height}')
        if obj.duration:
            info.append(f'{obj.duration}秒')
        if obj.file_size:
            size_mb = obj.file_size / (1024 * 1024)
            info.append(f'{size_mb:.1f}MB')
        return ' | '.join(info) if info else '-'

    file_info.short_description = '文件信息'


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['post', 'author', 'content_preview', 'like_count', 'reply_count', 'is_author_reply', 'is_featured',
                    'created_at']
    list_filter = ['is_author_reply', 'is_featured', 'is_deleted', 'created_at']
    search_fields = ['content', 'author__username', 'post__title']
    readonly_fields = ['like_count', 'reply_count', 'ip_address']

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content

    content_preview.short_description = '评论内容'

    actions = ['feature_comments', 'unfeature_comments', 'delete_comments']

    def feature_comments(self, request, queryset):
        count = queryset.update(is_featured=True)
        self.message_user(request, f'成功精选 {count} 条评论')

    feature_comments.short_description = "设为精选评论"

    def unfeature_comments(self, request, queryset):
        count = queryset.update(is_featured=False)
        self.message_user(request, f'成功取消精选 {count} 条评论')

    unfeature_comments.short_description = "取消精选"

    def delete_comments(self, request, queryset):
        count = queryset.update(is_deleted=True)
        self.message_user(request, f'成功删除 {count} 条评论')

    delete_comments.short_description = "删除评论"


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'creator', 'status', 'stats_display', 'is_official', 'is_trending', 'created_at']
    list_filter = ['status', 'is_official', 'is_trending', 'is_featured', 'created_at']
    search_fields = ['name', 'description', 'creator__username']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['post_count', 'participant_count', 'follow_count', 'view_count', 'hot_score']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'slug', 'description', 'cover_image', 'creator')
        }),
        ('话题属性', {
            'fields': ('is_official', 'is_trending', 'is_featured', 'status')
        }),
        ('审核信息', {
            'fields': ('reviewer', 'review_note', 'reject_reason', 'reviewed_at'),
            'classes': ('collapse',)
        }),
        ('统计数据', {
            'fields': ('post_count', 'participant_count', 'follow_count', 'view_count', 'hot_score'),
            'classes': ('collapse',)
        })
    )

    def stats_display(self, obj):
        return format_html(
            '📝 {} | 👥 {} | ❤️ {} | 👁️ {}',
            obj.post_count, obj.participant_count, obj.follow_count, obj.view_count
        )

    stats_display.short_description = '统计数据'

    actions = ['approve_topics', 'reject_topics', 'make_trending', 'remove_trending']

    def approve_topics(self, request, queryset):
        count = queryset.update(status='approved', reviewer=request.user, reviewed_at=timezone.now())
        self.message_user(request, f'成功通过 {count} 个话题的审核')

    approve_topics.short_description = "通过审核"

    def reject_topics(self, request, queryset):
        count = queryset.update(status='rejected', reviewer=request.user, reviewed_at=timezone.now())
        self.message_user(request, f'成功拒绝 {count} 个话题')

    reject_topics.short_description = "拒绝审核"

    def make_trending(self, request, queryset):
        count = queryset.update(is_trending=True)
        self.message_user(request, f'成功设置 {count} 个话题为热门')

    make_trending.short_description = "设为热门话题"

    def remove_trending(self, request, queryset):
        count = queryset.update(is_trending=False)
        self.message_user(request, f'成功取消 {count} 个话题的热门状态')

    remove_trending.short_description = "取消热门"


@admin.register(UserAction)
class UserActionAdmin(admin.ModelAdmin):
    list_display = ['user', 'action_type', 'target_info', 'ip_address', 'created_at']
    list_filter = ['action_type', 'created_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['user', 'action_type', 'post', 'comment', 'target_user', 'topic', 'ip_address', 'user_agent']

    def target_info(self, obj):
        if obj.post:
            return f'帖子: {obj.post.title}'
        elif obj.comment:
            return f'评论: {obj.comment.content[:30]}...'
        elif obj.target_user:
            return f'用户: {obj.target_user.username}'
        elif obj.topic:
            return f'话题: {obj.topic.name}'
        return '-'

    target_info.short_description = '目标对象'

    def has_add_permission(self, request):
        return False  # 禁止手动添加用户行为记录


@admin.register(ReviewLog)
class ReviewLogAdmin(admin.ModelAdmin):
    list_display = ['content_info', 'reviewer', 'action', 'status_change', 'created_at']
    list_filter = ['content_type', 'action', 'created_at']
    search_fields = ['reviewer__username', 'reason', 'note']
    readonly_fields = ['content_type', 'content_id', 'reviewer', 'action', 'old_status', 'new_status']

    def content_info(self, obj):
        return f'{obj.get_content_type_display()} ID: {obj.content_id}'

    content_info.short_description = '内容信息'

    def status_change(self, obj):
        if obj.old_status and obj.new_status:
            return f'{obj.old_status} → {obj.new_status}'
        return obj.new_status or '-'

    status_change.short_description = '状态变更'

    def has_add_permission(self, request):
        return False


@admin.register(SensitiveWord)
class SensitiveWordAdmin(admin.ModelAdmin):
    list_display = ['word', 'word_type', 'category', 'replacement', 'severity', 'hit_count', 'is_active']
    list_editable = ['word_type', 'category', 'replacement', 'severity', 'is_active']
    list_filter = ['word_type', 'category', 'severity', 'is_active']
    search_fields = ['word']
    readonly_fields = ['hit_count']

    actions = ['activate_words', 'deactivate_words']

    def activate_words(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'成功启用 {count} 个敏感词')

    activate_words.short_description = "启用敏感词"

    def deactivate_words(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'成功禁用 {count} 个敏感词')

    deactivate_words.short_description = "禁用敏感词"


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['reporter', 'content_info', 'report_type', 'status', 'handler', 'created_at']
    list_filter = ['report_type', 'content_type', 'status', 'created_at']
    search_fields = ['reporter__username', 'reason']
    readonly_fields = ['reporter', 'content_type', 'content_id', 'report_type', 'reason', 'evidence', 'ip_address']

    fieldsets = (
        ('举报信息', {
            'fields': ('reporter', 'content_type', 'content_id', 'report_type', 'reason', 'evidence', 'ip_address')
        }),
        ('处理信息', {
            'fields': ('status', 'handler', 'handle_note', 'handled_at')
        })
    )

    def content_info(self, obj):
        return f'{obj.get_content_type_display()} ID: {obj.content_id}'

    content_info.short_description = '举报内容'

    actions = ['resolve_reports', 'reject_reports']

    def resolve_reports(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='resolved',
            handler=request.user,
            handled_at=timezone.now()
        )
        self.message_user(request, f'成功处理 {count} 个举报')

    resolve_reports.short_description = "标记为已处理"

    def reject_reports(self, request, queryset):
        count = queryset.filter(status='pending').update(
            status='rejected',
            handler=request.user,
            handled_at=timezone.now()
        )
        self.message_user(request, f'成功驳回 {count} 个举报')

    reject_reports.short_description = "驳回举报"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['receiver', 'notification_type', 'title', 'sender', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read', 'created_at']
    search_fields = ['receiver__username', 'sender__username', 'title', 'content']
    readonly_fields = ['receiver', 'sender', 'notification_type', 'post', 'comment', 'title', 'content']

    actions = ['mark_as_read']

    def mark_as_read(self, request, queryset):
        count = queryset.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        self.message_user(request, f'成功标记 {count} 条通知为已读')

    mark_as_read.short_description = "标记为已读"


@admin.register(PostView)
class PostViewAdmin(admin.ModelAdmin):
    list_display = ['user', 'post', 'view_count', 'duration', 'source', 'created_at']
    list_filter = ['source', 'created_at']
    search_fields = ['user__username', 'post__title']
    readonly_fields = ['user', 'post', 'view_count', 'duration', 'source', 'ip_address']

    def has_add_permission(self, request):
        return False


@admin.register(UserFollow)
class UserFollowAdmin(admin.ModelAdmin):
    list_display = ['follower', 'following', 'is_mutual', 'created_at']
    list_filter = ['is_mutual', 'created_at']
    search_fields = ['follower__username', 'following__username']
    readonly_fields = ['follower', 'following', 'is_mutual']

    def has_add_permission(self, request):
        return False


@admin.register(PostCollection)
class PostCollectionAdmin(admin.ModelAdmin):
    list_display = ['user', 'post', 'folder', 'note', 'created_at']
    list_filter = ['folder', 'created_at']
    search_fields = ['user__username', 'post__title', 'folder']
    readonly_fields = ['user', 'post']


@admin.register(BlockedUser)
class BlockedUserAdmin(admin.ModelAdmin):
    list_display = ['user', 'blocked_user', 'reason', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'blocked_user__username', 'reason']
    readonly_fields = ['user', 'blocked_user']


# 自定义管理界面标题
admin.site.site_header = '萌宠社区管理后台'
admin.site.site_title = '萌宠社区'
admin.site.index_title = '社区管理'