from rest_framework import serializers
from .models import Feedback


class FeedbackSerializer(serializers.ModelSerializer):
    """反馈序列化器"""
    feedback_type_display = serializers.CharField(source='get_feedback_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True, default='匿名用户')

    class Meta:
        model = Feedback
        fields = [
            'id', 'user', 'username', 'feedback_type', 'feedback_type_display',
            'content', 'contact_info', 'status', 'status_display',
            'reply', 'created_at', 'updated_at'
        ]
        read_only_fields = ['user', 'status', 'reply', 'created_at', 'updated_at']

    def create(self, validated_data):
        # 自动关联当前登录用户（如果已登录）
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['user'] = request.user
        return super().create(validated_data)


class FeedbackAdminSerializer(serializers.ModelSerializer):
    """管理员用序列化器（可修改状态和回复）"""

    class Meta:
        model = Feedback
        fields = '__all__'
        read_only_fields = ['user', 'created_at', 'updated_at']