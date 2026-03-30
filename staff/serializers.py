
from rest_framework import serializers


class StaffLoginSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True, help_text='手机号')
    password = serializers.CharField(required=True, write_only=True, help_text='密码')


class StaffInfoSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    avatar = serializers.URLField(read_only=True)
    gender = serializers.CharField(read_only=True)
    integral = serializers.IntegerField(read_only=True)
    is_worked = serializers.BooleanField(read_only=True)
    last_login = serializers.DateTimeField(read_only=True)