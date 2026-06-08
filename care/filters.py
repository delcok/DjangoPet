# -*- coding: utf-8 -*-
import django_filters as filters

from .models import Recipe, CareActivity, CareRule, FeedingRule, Ingredient, CareTask


class IngredientFilter(filters.FilterSet):
    name = filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Ingredient
        fields = ["category", "common_allergen", "is_active", "name"]


class RecipeFilter(filters.FilterSet):
    category = filters.CharFilter(field_name="category__code")        # dog / cat
    category_id = filters.NumberFilter(field_name="category_id")
    tag = filters.CharFilter(field_name="functional_tags__code")      # 按功能标签 code
    title = filters.CharFilter(field_name="title", lookup_expr="icontains")

    class Meta:
        model = Recipe
        fields = ["category", "category_id", "life_stage", "day_index", "status", "is_active", "tag", "title"]


class FeedingRuleFilter(filters.FilterSet):
    category = filters.CharFilter(field_name="category__code")

    class Meta:
        model = FeedingRule
        fields = ["category", "life_stage"]


class CareActivityFilter(filters.FilterSet):
    category = filters.CharFilter(field_name="category__code")

    class Meta:
        model = CareActivity
        fields = ["category", "task_type", "life_stage", "is_active"]


class CareRuleFilter(filters.FilterSet):
    category = filters.CharFilter(field_name="category__code")

    class Meta:
        model = CareRule
        fields = ["category", "task_type", "life_stage", "is_active"]


class CareTaskFilter(filters.FilterSet):
    pet = filters.NumberFilter(field_name="pet_id")
    date = filters.DateFilter(field_name="date")
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = CareTask
        fields = ["pet", "care_plan", "date", "date_from", "date_to", "task_type", "status"]