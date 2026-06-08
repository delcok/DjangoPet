# -*- coding: utf-8 -*-
from django.contrib import admin

from .models import (
    Ingredient, FunctionalTag, FeedingRule, Recipe, RecipeIngredient,
    PetCareProfile, CareActivity, CareRule, CarePlan, CareTask,
)


# ---- 内联 ----
class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 1
    autocomplete_fields = ["ingredient"]   # 依赖 IngredientAdmin.search_fields


class CareTaskInline(admin.TabularInline):
    model = CareTask
    extra = 0
    fields = ["date", "scheduled_start", "scheduled_end", "task_type", "title", "status"]
    readonly_fields = fields
    show_change_link = True
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


# ---- 内容类 ----
@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "kcal_per_100g", "common_allergen", "is_active"]
    list_filter = ["category", "common_allergen", "is_active"]
    search_fields = ["name", "name_en"]
    filter_horizontal = ["toxic_to_categories"]
    list_editable = ["is_active"]


@admin.register(FunctionalTag)
class FunctionalTagAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]
    search_fields = ["code", "name"]
    list_editable = ["is_active"]


@admin.register(FeedingRule)
class FeedingRuleAdmin(admin.ModelAdmin):
    list_display = ["category", "life_stage", "meals_per_day", "mer_factor_min", "mer_factor_max",
                    "age_min_months", "age_max_months"]
    list_filter = ["category", "life_stage"]


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "life_stage", "day_index", "est_kcal_per_100g", "status", "is_active"]
    list_filter = ["category", "life_stage", "status", "is_active", "functional_tags"]
    search_fields = ["title", "primary_benefits"]
    filter_horizontal = ["functional_tags"]
    raw_id_fields = ["breed"]
    inlines = [RecipeIngredientInline]
    list_editable = ["status", "is_active"]


@admin.register(CareActivity)
class CareActivityAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "task_type", "life_stage", "duration_min", "difficulty", "weight", "is_active"]
    list_filter = ["category", "task_type", "life_stage", "is_active"]
    search_fields = ["title", "instructions"]
    list_editable = ["weight", "is_active"]


@admin.register(CareRule)
class CareRuleAdmin(admin.ModelAdmin):
    list_display = ["category", "task_type", "life_stage", "frequency_per_day", "default_duration_min", "is_active"]
    list_filter = ["category", "task_type", "life_stage", "is_active"]


# ---- 用户私有 ----
@admin.register(PetCareProfile)
class PetCareProfileAdmin(admin.ModelAdmin):
    list_display = ["pet", "activity_level", "food_preference", "enable_reminders", "updated_at"]
    list_filter = ["activity_level", "food_preference", "enable_reminders"]
    raw_id_fields = ["pet"]
    filter_horizontal = ["allergies", "disliked_ingredients"]


@admin.register(CarePlan)
class CarePlanAdmin(admin.ModelAdmin):
    list_display = ["id", "pet", "start_date", "end_date", "status", "meals_per_day",
                    "daily_kcal_target", "created_at"]
    list_filter = ["status", "start_date"]
    raw_id_fields = ["pet"]
    date_hierarchy = "start_date"
    inlines = [CareTaskInline]


@admin.register(CareTask)
class CareTaskAdmin(admin.ModelAdmin):
    list_display = ["id", "pet", "date", "scheduled_start", "scheduled_end",
                    "task_type", "title", "status"]
    list_filter = ["task_type", "status", "date"]
    search_fields = ["title", "tip_text"]
    raw_id_fields = ["care_plan", "pet", "recipe", "activity"]
    date_hierarchy = "date"