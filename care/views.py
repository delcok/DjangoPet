# -*- coding: utf-8 -*-
"""DRF 视图集(按受众拆分,风格对齐 bill 等模块)。
   用户端 User*: UserAuthentication + IsActiveUser,私有数据按 pet__owner 隔离。
   管理端 Admin*: ManagerAuthentication + IsManager,内容全 CRUD + 计划/待办只读监管。
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend

# ⚠️ 改成你项目里 JWT 认证 / 权限模块的实际路径
from utils.authentication import UserAuthentication, ManagerAuthentication
from utils.permission import IsActiveUser, IsManager
# 若用模块化权限,可把管理端 IsManager 换成 HasModuleAccess 并在 viewset 上加 required_module = 'care'

from pet.models import Pet
from .models import (
    Ingredient, FunctionalTag, FeedingRule, Recipe, RecipeIngredient,
    PetCareProfile, CareActivity, CareRule, CarePlan, CareTask,
)
from .serializers import (
    IngredientSerializer, FunctionalTagSerializer, FeedingRuleSerializer,
    RecipeListSerializer, RecipeDetailSerializer, CareActivitySerializer, CareRuleSerializer,
    PetCareProfileSerializer, CarePlanSerializer, CareTaskSerializer, CarePlanGenerateSerializer,
    AdminIngredientSerializer, AdminFunctionalTagSerializer, AdminFeedingRuleSerializer,
    AdminRecipeSerializer, AdminRecipeIngredientSerializer,
    AdminCareActivitySerializer, AdminCareRuleSerializer,
)
from .filters import (
    IngredientFilter, RecipeFilter, FeedingRuleFilter,
    CareActivityFilter, CareRuleFilter, CareTaskFilter,
)
from .pagination import StandardResultsSetPagination, LargeResultsSetPagination


# ============================================================
# 用户端(C 端):宠物主
# ============================================================
class UserIngredientViewSet(viewsets.ReadOnlyModelViewSet):
    """食材库(只读),供过敏/挑食选择器用"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    queryset = Ingredient.objects.filter(is_active=True)
    serializer_class = IngredientSerializer
    pagination_class = LargeResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = IngredientFilter
    search_fields = ["name", "name_en"]
    ordering = ["category", "name"]


class UserFunctionalTagViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    queryset = FunctionalTag.objects.filter(is_active=True)
    serializer_class = FunctionalTagSerializer
    pagination_class = None


class UserRecipeViewSet(viewsets.ReadOnlyModelViewSet):
    """食谱库(只读,仅已发布)"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    queryset = (Recipe.objects.filter(is_active=True, status="published")
                .select_related("category", "breed")
                .prefetch_related("items__ingredient", "functional_tags"))
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = RecipeFilter
    search_fields = ["title", "primary_benefits"]
    ordering_fields = ["day_index", "est_kcal_per_100g", "created_at"]
    ordering = ["day_index"]

    def get_serializer_class(self):
        return RecipeDetailSerializer if self.action == "retrieve" else RecipeListSerializer


class UserCareActivityViewSet(viewsets.ReadOnlyModelViewSet):
    """护理活动库(只读)"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    queryset = CareActivity.objects.filter(is_active=True).select_related("category")
    serializer_class = CareActivitySerializer
    pagination_class = LargeResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = CareActivityFilter
    search_fields = ["title", "instructions"]
    ordering_fields = ["task_type", "difficulty", "weight"]


class UserPetCareProfileViewSet(viewsets.ModelViewSet):
    """养育档案(仅本人宠物)"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    serializer_class = PetCareProfileSerializer

    def get_queryset(self):
        return (PetCareProfile.objects
                .filter(pet__owner=self.request.user)
                .select_related("pet")
                .prefetch_related("allergies", "disliked_ingredients"))


class UserCarePlanViewSet(viewsets.ModelViewSet):
    """养育计划(仅本人);generate 生成一段日程"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    serializer_class = CarePlanSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["pet", "status"]
    ordering_fields = ["start_date", "created_at"]
    ordering = ["-start_date"]

    def get_queryset(self):
        return CarePlan.objects.filter(pet__owner=self.request.user).select_related("pet")

    @action(detail=False, methods=["post"])
    def generate(self, request):
        ser = CarePlanGenerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        pet = get_object_or_404(Pet, id=ser.validated_data["pet"], owner=request.user)
        try:
            from .services import generate_care_plan  # 下一步实现
        except ImportError:
            return Response(
                {"detail": "生成服务尚未实现:请先创建 care/services.py 的 generate_care_plan()"},
                status=status.HTTP_501_NOT_IMPLEMENTED,
            )
        plan = generate_care_plan(
            pet, start_date=ser.validated_data.get("start_date"),
            days=ser.validated_data.get("days", 7),
        )
        return Response(CarePlanSerializer(plan, context={"request": request}).data,
                        status=status.HTTP_201_CREATED)


class UserCareTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """待办只读 + 打卡(complete/skip);today 拉当天待办。仅本人宠物。"""
    authentication_classes = [UserAuthentication]
    permission_classes = [IsActiveUser]
    serializer_class = CareTaskSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = CareTaskFilter
    ordering_fields = ["date", "scheduled_start"]
    ordering = ["date", "scheduled_start"]

    def get_queryset(self):
        return (CareTask.objects
                .filter(pet__owner=self.request.user)
                .select_related("recipe", "activity", "pet"))

    @action(detail=False, methods=["get"])
    def today(self, request):
        qs = self.get_queryset().filter(date=timezone.localdate())
        pet_id = request.query_params.get("pet")
        if pet_id:
            qs = qs.filter(pet_id=pet_id)
        return Response(self.get_serializer(qs.order_by("scheduled_start", "id"), many=True).data)

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        task = self.get_object()
        task.status = "done"
        task.completed_at = timezone.now()
        note = request.data.get("completion_note")
        if note is not None:
            task.completion_note = note
        task.save(update_fields=["status", "completed_at", "completion_note", "updated_at"])
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=["post"])
    def skip(self, request, pk=None):
        task = self.get_object()
        task.status = "skipped"
        task.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(task).data)


# ============================================================
# 管理端:平台管理员(内容运营 + 监管)
# ============================================================
class _AdminContentViewSet(viewsets.ModelViewSet):
    """管理端内容基类:统一认证/权限/分页;查询不预过滤 is_active(管理员可见停用项)"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    # required_module = 'care'   # 若把权限换成 HasModuleAccess 时启用


class AdminIngredientViewSet(_AdminContentViewSet):
    queryset = Ingredient.objects.all().prefetch_related("toxic_to_categories")
    serializer_class = AdminIngredientSerializer
    filterset_class = IngredientFilter
    search_fields = ["name", "name_en"]
    ordering = ["category", "name"]


class AdminFunctionalTagViewSet(_AdminContentViewSet):
    queryset = FunctionalTag.objects.all()
    serializer_class = AdminFunctionalTagSerializer
    filterset_fields = ["is_active"]
    search_fields = ["code", "name"]
    pagination_class = None


class AdminFeedingRuleViewSet(_AdminContentViewSet):
    queryset = FeedingRule.objects.select_related("category")
    serializer_class = AdminFeedingRuleSerializer
    filterset_class = FeedingRuleFilter
    pagination_class = None


class AdminRecipeViewSet(_AdminContentViewSet):
    queryset = (Recipe.objects.all()
                .select_related("category", "breed")
                .prefetch_related("items__ingredient", "functional_tags"))
    serializer_class = AdminRecipeSerializer
    filterset_class = RecipeFilter
    search_fields = ["title", "primary_benefits"]
    ordering_fields = ["day_index", "est_kcal_per_100g", "created_at"]
    ordering = ["category", "life_stage", "day_index"]


class AdminRecipeIngredientViewSet(_AdminContentViewSet):
    """食谱明细单独 CRUD(?recipe=<id> 过滤),避免嵌套写的复杂度"""
    queryset = RecipeIngredient.objects.select_related("ingredient", "recipe")
    serializer_class = AdminRecipeIngredientSerializer
    filterset_fields = ["recipe", "ingredient"]
    ordering = ["recipe", "order"]


class AdminCareActivityViewSet(_AdminContentViewSet):
    queryset = CareActivity.objects.all().select_related("category")
    serializer_class = AdminCareActivitySerializer
    filterset_class = CareActivityFilter
    search_fields = ["title", "instructions"]
    ordering = ["category", "task_type"]


class AdminCareRuleViewSet(_AdminContentViewSet):
    queryset = CareRule.objects.all().select_related("category")
    serializer_class = AdminCareRuleSerializer
    filterset_class = CareRuleFilter
    pagination_class = None


class AdminCarePlanViewSet(viewsets.ReadOnlyModelViewSet):
    """计划监管(只读,全量),便于排查/客服"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    queryset = CarePlan.objects.select_related("pet")
    serializer_class = CarePlanSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["pet", "status"]
    ordering = ["-start_date"]


class AdminCareTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """待办监管(只读,全量)"""
    authentication_classes = [ManagerAuthentication]
    permission_classes = [IsManager]
    queryset = CareTask.objects.select_related("recipe", "activity", "pet")
    serializer_class = CareTaskSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = CareTaskFilter
    ordering = ["date", "scheduled_start"]