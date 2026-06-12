# -*- coding: utf-8 -*-
# @Time    : 2026/6/8 16:42
# @Author  : Delock

# -*- coding: utf-8 -*-
"""
养育日程生成引擎(纯函数,不使用信号)。
入口: generate_care_plan(pet, start_date=None, days=7) —— 由 UserCarePlanViewSet.generate 显式调用。

流水线:
  1) 解析 life_stage(Pet.age_months + FeedingRule 阈值,special_phase 兜底)
  2) 算每日能量 DER = RER × 系数(绝育/活动/体况/特殊期修正)
  3) 取候选食谱(排除过敏原、对该物种有毒的食材),种子随机洗牌 + 排除近 K 天用过
  4) 取护理规则 + 活动库(按 raising_mode 过滤),加权随机 + 排重
  5) 按 feed_windows / time_windows 把任务排成"时间区间",落 CareTask(喂食带份量与快照)

能量公式(兽医营养学常用):
  RER = 70 × 体重kg^0.75 ;  DER = RER × 系数
"""
import random
from datetime import datetime, timedelta, time, date as date_cls
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from pet.models import Pet
from .models import (
    FeedingRule, Recipe, CareActivity, CareRule, CarePlan, CareTask,
)

# ---- 系数表(可按需调整)----
ACTIVITY_ADJ = {"low": 0.9, "moderate": 1.0, "high": 1.1}
BCS_ADJ = {1: 1.2, 2: 1.1, 3: 1.0, 4: 0.9, 5: 0.8}      # 体况评分 1-5
PHASE_ADJ = {"pregnant": 1.6, "lactating": 2.5}          # 其余阶段不额外加成
ANTI_REPEAT_DAYS = 6                                      # 近 N 天内尽量不重复
DEFAULT_FEED_WINDOWS = {1: [("07:30", "08:30")],
                        2: [("07:30", "08:30"), ("17:30", "18:30")],
                        3: [("07:00", "08:00"), ("12:30", "13:30"), ("18:00", "19:00")],
                        4: [("06:30", "07:30"), ("11:00", "12:00"), ("16:00", "17:00"), ("20:00", "21:00")]}


# ============================================================
# 小工具
# ============================================================
def _parse_t(s):
    h, m = str(s).split(":")
    return time(int(h), int(m))

def _aware(d, t):
    dt = datetime.combine(d, t)
    if getattr(settings, "USE_TZ", False):
        return timezone.make_aware(dt)
    return dt

def _meal_title(idx, total):
    table = {1: ["正餐"], 2: ["早餐", "晚餐"], 3: ["早餐", "午餐", "晚餐"],
             4: ["早餐", "上午加餐", "午餐", "晚餐"]}
    names = table.get(total)
    return names[idx] if names and idx < len(names) else f"第{idx + 1}餐"


# ============================================================
# 1) 年龄段
# ============================================================
def resolve_life_stage(pet, rules_by_stage):
    months = pet.age_months
    if months is not None:
        for ls, rule in rules_by_stage.items():
            lo = rule.age_min_months or 0
            hi = rule.age_max_months
            if months >= lo and (hi is None or months < hi):
                return ls
    # 生日未知:用 special_phase 兜底
    sp = getattr(pet, "special_phase", None)
    if sp in ("juvenile", "senior"):
        return sp
    return "adult"


# ============================================================
# 2) 能量 DER
# ============================================================
def compute_der(pet, profile, rule):
    """返回 (der_or_None, factor)。无体重则 der=None(份量退回参考区间)。"""
    # 绝育取系数下限、未绝育取上限(绝育后代谢更低)
    factor = float(rule.mer_factor_min if getattr(pet, "is_neutered", False) else rule.mer_factor_max)
    activity = getattr(profile, "activity_level", "moderate") if profile else "moderate"
    factor *= ACTIVITY_ADJ.get(activity, 1.0)
    bcs = getattr(pet, "body_condition_score", None)
    if bcs in BCS_ADJ:
        factor *= BCS_ADJ[bcs]
    factor *= PHASE_ADJ.get(getattr(pet, "special_phase", None), 1.0)

    weight = pet.weight
    if not weight:
        return None, factor
    rer = 70.0 * (float(weight) ** 0.75)
    return rer * factor, factor


def _portion_per_meal(der, est_kcal_per_100g, meals, ref_min, ref_max):
    """每餐克数:能量优先,无体重退回参考区间中点;并夹在参考区间内。"""
    per = None
    if der and est_kcal_per_100g:
        per = (der / (float(est_kcal_per_100g) / 100.0)) / max(meals, 1)
    elif ref_min and ref_max:
        per = (float(ref_min) + float(ref_max)) / 2.0
    if per is None:
        return None, None
    if ref_min and ref_max:                      # 安全兜底:夹在单餐参考区间内
        per = max(float(ref_min), min(per, float(ref_max)))
    per = round(per)
    kcal = round(per * float(est_kcal_per_100g) / 100.0) if est_kcal_per_100g else None
    return per, kcal


# ============================================================
# 3/4) 候选与挑选(种子随机 + 排重 + 加权)
# ============================================================
def _candidate_recipes(category, life_stage, allergen_ids):
    qs = (Recipe.objects.filter(category=category, life_stage=life_stage,
                                status="published", is_active=True)
          .prefetch_related("items__ingredient"))
    if allergen_ids:
        qs = qs.exclude(items__ingredient_id__in=allergen_ids)
    qs = qs.exclude(items__ingredient__toxic_to_categories=category)   # 毒性护栏
    return list(qs.distinct())


def _activities(category, task_type, life_stage, raising_mode):
    qs = (CareActivity.objects.filter(category=category, task_type=task_type, is_active=True)
          .filter(Q(life_stage="") | Q(life_stage=life_stage)))
    return [a for a in qs
            if not a.applies_raising_modes or (raising_mode and raising_mode in a.applies_raising_modes)]


def _care_rules(category, life_stage, raising_mode):
    qs = (CareRule.objects.filter(category=category, is_active=True)
          .filter(Q(life_stage="") | Q(life_stage=life_stage)))
    return [r for r in qs
            if not r.applies_raising_modes or (raising_mode and raising_mode in r.applies_raising_modes)]


def _recent_ids(pet, before, field):
    since = before - timedelta(days=ANTI_REPEAT_DAYS)
    f = {"pet": pet, "date__gte": since, "date__lt": before, f"{field}__isnull": False}
    return set(CareTask.objects.filter(**f).values_list(f"{field}_id", flat=True))


def _pick(order, avoid):
    """按给定顺序取第一个不在 avoid 里的;都用过则放开取第一个。"""
    for x in order:
        if x.id not in avoid:
            return x
    return order[0] if order else None


def _shuffled(rng, items):
    out = list(items)
    rng.shuffle(out)
    return out


def _weighted_order(rng, items):
    """按 weight 加权洗牌(权重大更靠前)。"""
    return sorted(items, key=lambda a: rng.random() ** (1.0 / max(getattr(a, "weight", 1), 1)), reverse=True)


# ============================================================
# 入口
# ============================================================
@transaction.atomic
def generate_care_plan(pet, start_date=None, days=7):
    # 锁住该宠物行,把"同一宠物"的并发/重复生成串行化。
    # 否则两个并发请求会各自 archive(彼此看不见对方未提交的新计划)再各自 create,
    # 最终留下 2 个 active 计划(典型的"快速点两次生成"出现重复)。
    # 注意:这里故意不 select_related("category")——category 是 PROTECT 外键、
    #       且同一大类下很多宠物共用同一行,连它一起锁会让"不同宠物"的生成也互相阻塞;
    #       单表 SELECT ... FOR UPDATE 只锁宠物自己这行即可,下面 pet.category 再走一次普通查询代价可忽略。
    #       (select_for_update 在 SQLite 上是空操作,这条并发保护需到 MySQL/PostgreSQL 验证。)
    pet = Pet.objects.select_for_update().get(pk=pet.pk)

    category = pet.category
    start_date = start_date or timezone.localdate()
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    end_date = start_date + timedelta(days=days - 1)

    # 该物种的全部投喂规则(按年龄段索引)
    rules_by_stage = {r.life_stage: r for r in FeedingRule.objects.filter(category=category)}
    if not rules_by_stage:
        raise ValueError(f"缺少 {getattr(category, 'code', category)} 的 FeedingRule,请先导入种子数据")

    life_stage = resolve_life_stage(pet, rules_by_stage)
    feed_rule = rules_by_stage.get(life_stage) or next(iter(rules_by_stage.values()))

    profile = getattr(pet, "care_profile", None)
    der, _factor = compute_der(pet, profile, feed_rule)

    # 喂食时间窗:个人偏好 > 规则 > 默认
    feed_windows = (getattr(profile, "preferred_feeding_windows", None)
                    or feed_rule.feed_windows
                    or DEFAULT_FEED_WINDOWS.get(feed_rule.meals_per_day, DEFAULT_FEED_WINDOWS[2]))
    meals = len(feed_windows)

    # 过敏原 + 候选食谱
    allergen_ids = set(profile.allergies.values_list("id", flat=True)) if profile else set()
    recipes = _candidate_recipes(category, life_stage, allergen_ids)
    if not recipes:
        raise ValueError("无可用食谱(可能过敏原排除过多或种子数据缺失)")

    # 护理规则
    raising_mode = getattr(pet, "raising_mode", None)
    care_rules = _care_rules(category, life_stage, raising_mode)

    # 种子(同一宠物同一周稳定可复现)
    iso = start_date.isocalendar()
    seed = (pet.id * 100000 + iso[0] * 100 + iso[1]) & 0x7FFFFFFF
    rng = random.Random(seed)

    enable_reminder = getattr(profile, "enable_reminders", True) if profile else True

    # 归档同宠物旧的进行中计划,保证只有一个 active
    CarePlan.objects.filter(pet=pet, status="active").update(status="archived")

    plan = CarePlan.objects.create(
        pet=pet, start_date=start_date, end_date=end_date, status="active",
        weight_at_generation=pet.weight,
        life_stage_at_generation=life_stage,
        daily_kcal_target=Decimal(str(round(der, 1))) if der else None,
        meals_per_day=meals,
        generation_seed=seed,
        algorithm_version="v1",
    )

    # 排重状态(从近 K 天历史起步,周内也不重复)
    used_recipe = _recent_ids(pet, start_date, "recipe")
    used_activity = {}  # task_type -> set(activity_id)

    recipe_order_base = _shuffled(rng, recipes)
    tasks = []

    for offset in range(days):
        d = start_date + timedelta(days=offset)

        # —— 当天食谱(整天一套,份量按餐数拆)——
        if len(used_recipe) >= len(recipes):
            used_recipe = set()  # 一轮用尽,放开下一轮
        recipe = _pick(recipe_order_base, used_recipe) or recipe_order_base[0]
        used_recipe.add(recipe.id)

        per_meal_g, per_meal_kcal = _portion_per_meal(
            der, recipe.est_kcal_per_100g, meals, recipe.ref_portion_min_g, recipe.ref_portion_max_g)
        snapshot = [{"ingredient": it.ingredient.name, "amount": float(it.amount), "unit": it.unit}
                    for it in recipe.items.all()]

        for idx, win in enumerate(feed_windows):
            t_start, t_end = _parse_t(win[0]), _parse_t(win[1])
            tasks.append(CareTask(
                care_plan=plan, pet=pet, task_type="feed", date=d,
                scheduled_start=t_start, scheduled_end=t_end,
                title=_meal_title(idx, meals),
                tip_text=(recipe.primary_benefits or "")[:255],
                recipe=recipe, portion_g=per_meal_g, kcal=per_meal_kcal,
                ingredients_snapshot=snapshot,
                reminder_at=_aware(d, t_start) if enable_reminder else None,
                status="pending",
            ))

        # —— 当天非喂食任务 ——
        for rule in care_rules:
            windows = rule.time_windows or [("19:00", "20:00")]
            acts = _activities(category, rule.task_type, life_stage, raising_mode)
            order = _weighted_order(rng, acts) if acts else []
            avoid = used_activity.setdefault(rule.task_type, set())
            if acts and len(avoid) >= len(acts):
                avoid.clear()

            for i in range(rule.frequency_per_day):
                win = windows[i] if i < len(windows) else windows[-1]
                t_start, t_end = _parse_t(win[0]), _parse_t(win[1])
                act = _pick(order, avoid) if order else None
                if act:
                    avoid.add(act.id)
                dur = (act.duration_min if act else None) or rule.default_duration_min
                tasks.append(CareTask(
                    care_plan=plan, pet=pet, task_type=rule.task_type, date=d,
                    scheduled_start=t_start, scheduled_end=t_end,
                    title=(act.title if act else rule.get_task_type_display()),
                    tip_text=((act.tip_text if act else "") or rule.tip_text or "")[:255],
                    activity=act,
                    payload={"duration_min": dur} if dur else {},
                    reminder_at=_aware(d, t_start) if enable_reminder else None,
                    status="pending",
                ))

    CareTask.objects.bulk_create(tasks)
    return plan