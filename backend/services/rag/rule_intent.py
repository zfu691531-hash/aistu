# -*- coding: utf-8 -*-
"""Rule intent inference and structured metadata helpers."""

from __future__ import annotations

import re


INTENT_KEYWORDS = {
    "attendance": ["迟到", "考勤", "缺勤", "旷课", "早退", "到校", "请假", "返校"],
    "classroom": ["课堂", "上课", "课堂纪律", "喧哗", "扰乱秩序", "走动", "顶撞"],
    "phone": ["手机", "电子设备", "智能手表", "终端"],
    "behavior": ["违纪", "冲突", "欺凌", "威胁", "围堵", "打架", "辱骂"],
    "home_school": ["家长", "家校", "联系家长", "沟通家长"],
    "care": ["关怀", "跟进", "支持", "情绪", "安全感", "观察"],
}


def infer_query_intent(query: str) -> dict:
    text = (query or "").strip().lower()
    themes: list[str] = []
    matched_terms: list[str] = []

    for theme, keywords in INTENT_KEYWORDS.items():
        hits = [keyword for keyword in keywords if keyword in text]
        if hits:
            themes.append(theme)
            matched_terms.extend(hits)

    return {
        "themes": themes,
        "matched_terms": list(dict.fromkeys(matched_terms)),
    }


def extract_structured_rule_meta(text: str, category: str | None = None) -> dict:
    body = (text or "").strip()
    meta = {
        "category": category or "",
        "theme": "",
        "behavior_types": [],
        "keywords": [],
        "parent_contact": "",
        "care_followup": "",
    }

    for line in body.splitlines():
        raw = line.strip()
        if not raw or ":" not in raw and "：" not in raw:
            continue
        normalized = raw.replace("：", ":", 1)
        key, value = normalized.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if not value:
            continue
        if key in {"主题", "theme"}:
            meta["theme"] = value
        elif key in {"行为类型", "behavior_types"}:
            meta["behavior_types"] = _split_meta_values(value)
        elif key in {"关键词", "keywords"}:
            meta["keywords"] = _split_meta_values(value)
        elif key in {"家校联系", "parent_contact"}:
            meta["parent_contact"] = value
        elif key in {"关怀跟进", "care_followup"}:
            meta["care_followup"] = value

    combined_keywords = list(dict.fromkeys(meta["keywords"] + meta["behavior_types"]))
    meta["keywords"] = combined_keywords
    return meta


def metadata_match_boost(query_intent: dict, meta: dict) -> float:
    themes = set(query_intent.get("themes") or [])
    matched_terms = set(query_intent.get("matched_terms") or [])
    meta_keywords = set(meta.get("keywords") or [])
    meta_category = meta.get("category") or ""
    meta_theme = meta.get("theme") or ""

    score = 0.0

    if "attendance" in themes and _contains_any(meta_category + meta_theme, ["考勤", "迟到", "早退", "旷课", "请假"]):
        score += 1.2
    if "classroom" in themes and _contains_any(meta_category + meta_theme, ["课堂", "纪律"]):
        score += 1.1
    if "phone" in themes and _contains_any(meta_category + meta_theme, ["手机", "电子设备", "终端"]):
        score += 1.2
    if "behavior" in themes and _contains_any(meta_category + meta_theme, ["行为", "冲突", "欺凌", "安全"]):
        score += 1.0
    if "home_school" in themes and (meta.get("parent_contact") or _contains_any(meta_category + meta_theme, ["家校", "家长"])):
        score += 0.8
    if "care" in themes and (meta.get("care_followup") or _contains_any(meta_category + meta_theme, ["关怀", "支持"])):
        score += 0.8

    keyword_hits = len(matched_terms.intersection(meta_keywords))
    score += keyword_hits * 0.35

    return round(score, 6)


def extract_structured_terms_for_keywords(text: str, category: str | None = None) -> list[str]:
    meta = extract_structured_rule_meta(text, category=category)
    terms = []
    for value in [meta.get("category"), meta.get("theme"), meta.get("parent_contact"), meta.get("care_followup")]:
        if value:
            terms.extend(_tokenish_terms(value))
    for item in meta.get("keywords") or []:
        terms.extend(_tokenish_terms(item))
    return list(dict.fromkeys([term for term in terms if term]))


def _split_meta_values(value: str) -> list[str]:
    parts = re.split(r"[、,，/|；;\s]+", value)
    return [item.strip() for item in parts if item.strip()]


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _tokenish_terms(value: str) -> list[str]:
    parts = re.split(r"[、,，/|；;]+", value)
    return [item.strip() for item in parts if item.strip()]
