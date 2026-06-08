# -*- coding: utf-8 -*-
from rest_framework import serializers

from .models import (
    Ingredient, FunctionalTag, FeedingRule, Recipe, RecipeIngredient,
    PetCareProfile, CareActivity, CareRule, CarePlan, CareTask,
)


# ============================================================
# 用户端(只读为主)
# ============================================================
class FunctionalTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FunctionalTag
        fields = ["id", "code", "name"]


class IngredientSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = Ingredient
        fields = ["id", "name", "name_en", "category", "category_display",
                  "kcal_per_100g", "common_allergen"]


class RecipeIngredientSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)
    unit_display = serializers.CharField(source="get_unit_display", read_only=True)

    class Meta:
        model = RecipeIngredient
        fields = ["id", "ingredient", "ingredient_name", "amount", "unit", "unit_display", "prep_note", "order"]


class RecipeListSerializer(serializers.ModelSerializer):
    category_code = serializers.CharField(source="category.code", read_only=True)
    life_stage_display = serializers.CharField(source="get_life_stage_display", read_only=True)
    tags = serializers.SlugRelatedField(source="functional_tags", slug_field="name", many=True, read_only=True)

    class Meta:
        model = Recipe
        fields = ["id", "title", "category_code", "life_stage", "life_stage_display",
                  "day_index", "primary_benefits", "est_kcal_per_100g", "tags"]


class RecipeDetailSerializer(RecipeListSerializer):
    items = RecipeIngredientSerializer(many=True, read_only=True)
    functional_tags = FunctionalTagSerializer(many=True, read_only=True)

    class Meta(RecipeListSerializer.Meta):
        fields = RecipeListSerializer.Meta.fields + [
            "preparation_steps", "ref_portion_min_g", "ref_portion_max_g",
            "status", "version", "items", "functional_tags",
        ]


class FeedingRuleSerializer(serializers.ModelSerializer):
    category_code = serializers.CharField(source="category.code", read_only=True)
    life_stage_display = serializers.CharField(source="get_life_stage_display", read_only=True)

    class Meta:
        model = FeedingRule
        fields = ["id", "category", "category_code", "life_stage", "life_stage_display",
                  "meals_per_day", "mer_factor_min", "mer_factor_max",
                  "age_min_months", "age_max_months", "feed_windows"]


class CareActivitySerializer(serializers.ModelSerializer):
    category_code = serializers.CharField(source="category.code", read_only=True)
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)

    class Meta:
        model = CareActivity
        fields = ["id", "category", "category_code", "task_type", "task_type_display",
                  "life_stage", "title", "instructions", "tip_text",
                  "duration_min", "difficulty", "media_url", "weight", "applies_raising_modes"]


class CareRuleSerializer(serializers.ModelSerializer):
    category_code = serializers.CharField(source="category.code", read_only=True)

    class Meta:
        model = CareRule
        fields = ["id", "category", "category_code", "life_stage", "task_type",
                  "frequency_per_day", "default_duration_min", "time_windows",
                  "applies_raising_modes", "tip_text"]


class PetCareProfileSerializer(serializers.ModelSerializer):
    allergy_names = serializers.SlugRelatedField(source="allergies", slug_field="name", many=True, read_only=True)
    disliked_names = serializers.SlugRelatedField(source="disliked_ingredients", slug_field="name", many=True, read_only=True)

    class Meta:
        model = PetCareProfile
        fields = ["id", "pet", "activity_level", "food_preference",
                  "allergies", "allergy_names", "disliked_ingredients", "disliked_names",
                  "preferred_feeding_windows", "preferred_walk_windows",
                  "walks_per_day_override", "enable_reminders"]

    def validate(self, attrs):
        request = self.context.get("request")
        pet = attrs.get("pet") or getattr(self.instance, "pet", None)
        if request and pet and pet.owner_id != request.user.id:
            raise serializers.ValidationError({"pet": "该宠物不属于当前用户"})
        if self.instance is None and pet and PetCareProfile.objects.filter(pet=pet).exists():
            raise serializers.ValidationError({"pet": "该宠物已存在养育档案,请用 PATCH 更新"})
        return attrs


class CarePlanSerializer(serializers.ModelSerializer):
    pet_name = serializers.CharField(source="pet.name", read_only=True)
    life_stage_display = serializers.CharField(source="get_life_stage_at_generation_display", read_only=True)
    task_count = serializers.SerializerMethodField()

    class Meta:
        model = CarePlan
        fields = ["id", "pet", "pet_name", "start_date", "end_date", "status",
                  "weight_at_generation", "life_stage_at_generation", "life_stage_display",
                  "daily_kcal_target", "meals_per_day", "algorithm_version",
                  "task_count", "created_at"]
        read_only_fields = ["weight_at_generation", "life_stage_at_generation",
                            "daily_kcal_target", "meals_per_day", "algorithm_version"]

    def get_task_count(self, obj):
        return obj.tasks.count()


class CareTaskSerializer(serializers.ModelSerializer):
    task_type_display = serializers.CharField(source="get_task_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    time_range = serializers.SerializerMethodField()
    recipe_title = serializers.SerializerMethodField()
    activity_title = serializers.SerializerMethodField()

    class Meta:
        model = CareTask
        fields = ["id", "care_plan", "pet", "task_type", "task_type_display",
                  "date", "scheduled_start", "scheduled_end", "time_range",
                  "title", "tip_text",
                  "recipe", "recipe_title", "portion_g", "kcal", "ingredients_snapshot",
                  "activity", "activity_title", "payload",
                  "reminder_at", "status", "status_display", "completed_at", "completion_note"]

    def get_time_range(self, obj):
        if obj.scheduled_start and obj.scheduled_end:
            return f"{obj.scheduled_start.strftime('%H:%M')}–{obj.scheduled_end.strftime('%H:%M')}"
        return None

    def get_recipe_title(self, obj):
        return obj.recipe.title if obj.recipe_id else None

    def get_activity_title(self, obj):
        return obj.activity.title if obj.activity_id else None


class CarePlanGenerateSerializer(serializers.Serializer):
    pet = serializers.IntegerField()
    start_date = serializers.DateField(required=False)
    days = serializers.IntegerField(required=False, default=7, min_value=1, max_value=31)


# ============================================================
# 管理端(全字段可写,含 M2M)
# ============================================================
class AdminIngredientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ingredient
        fields = ["id", "name", "name_en", "category", "kcal_per_100g",
                  "common_allergen", "toxic_to_categories", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class AdminFunctionalTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = FunctionalTag
        fields = ["id", "code", "name", "is_active"]


class AdminFeedingRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedingRule
        fields = ["id", "category", "life_stage", "meals_per_day",
                  "mer_factor_min", "mer_factor_max", "age_min_months",
                  "age_max_months", "feed_windows"]


class AdminRecipeIngredientSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)

    class Meta:
        model = RecipeIngredient
        fields = ["id", "recipe", "ingredient", "ingredient_name", "amount", "unit", "prep_note", "order"]


class AdminRecipeSerializer(serializers.ModelSerializer):
    # 明细只读展示;增删改走 admin/recipe-ingredients/?recipe=<id>
    items = RecipeIngredientSerializer(many=True, read_only=True)

    class Meta:
        model = Recipe
        fields = ["id", "category", "life_stage", "day_index", "breed",
                  "title", "primary_benefits", "preparation_steps", "est_kcal_per_100g",
                  "ref_portion_min_g", "ref_portion_max_g", "functional_tags",
                  "status", "version", "is_active", "items", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class AdminCareActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = CareActivity
        fields = ["id", "category", "task_type", "life_stage", "title", "instructions",
                  "tip_text", "duration_min", "difficulty", "media_url", "weight",
                  "applies_raising_modes", "is_active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class AdminCareRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CareRule
        fields = ["id", "category", "life_stage", "task_type", "frequency_per_day",
                  "default_duration_min", "time_windows", "applies_raising_modes",
                  "tip_text", "is_active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]