"""廉价评分模块 — 纯 Python 计算候选论文与研究问题的匹配度"""

import re
from typing import Optional


def keyword_overlap_score(text: str, keywords: list[str]) -> float:
    """标题/摘要关键词匹配 (0-3分)"""
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text_lower)
    return min(hits, 3.0)


def topic_match_score(paper_topics: list[str], question: dict) -> float:
    """OpenAlex topic 匹配 (0-2分)"""
    if not paper_topics:
        return 0.0

    question_terms = set()
    for kw in question.get("keywords", []):
        question_terms.add(kw.lower())
    for method in question.get("methods_of_interest", []):
        question_terms.add(method.lower())

    hits = 0
    for topic in paper_topics:
        topic_lower = topic.lower()
        for term in question_terms:
            if term in topic_lower or topic_lower in term:
                hits += 1
                break

    return min(hits, 2.0)


def seed_connection_score(seed_connections: list[str], question_seed_dois: list[str]) -> float:
    """种子连接数评分 (0-3分基础 + 2分多连接奖励)"""
    if not seed_connections or not question_seed_dois:
        return 0.0

    question_set = set(question_seed_dois)
    overlap = sum(1 for doi in seed_connections if doi in question_set)

    base = min(overlap, 3.0)
    bonus = 2.0 if overlap >= 3 else 0.0

    return base + bonus


def recency_score(year: Optional[int]) -> float:
    """年份加权 (0-1分)"""
    if not year:
        return 0.0

    current_year = 2026
    age = max(0, current_year - year)
    return max(0.0, 1.0 - age * 0.15)


def venue_match_score(venue_name: str, question: dict) -> float:
    """期刊/会议匹配 (0-1分)"""
    venues = question.get("venues", [])
    if not venues or not venue_name:
        return 0.0

    venue_lower = venue_name.lower()
    for v in venues:
        if v.lower() in venue_lower or venue_lower in v.lower():
            return 1.0
    return 0.0


def negative_keyword_penalty(text: str, negative_keywords: list[str]) -> float:
    """负面关键词惩罚 (-2分)"""
    if not negative_keywords:
        return 0.0

    text_lower = text.lower()
    for kw in negative_keywords:
        if kw.lower() in text_lower:
            return -2.0
    return 0.0


def score_candidate(
    paper: dict,
    question: dict,
    seed_connections: list[str] = None,
    negative_keywords: list[str] = None,
) -> dict:
    """计算候选论文对某个问题的综合匹配分。"""
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}"
    seed_conns = seed_connections or []
    neg_kws = negative_keywords or []

    components = {
        "keyword_overlap": keyword_overlap_score(text, question.get("keywords", [])),
        "topic_match": topic_match_score(paper.get("topics", []), question),
        "seed_connections": seed_connection_score(seed_conns, question.get("seed_dois", [])),
        "recency": recency_score(paper.get("year")),
        "venue_match": venue_match_score(
            paper.get("source", {}).get("name", ""), question
        ),
        "negative_penalty": negative_keyword_penalty(text, neg_kws),
    }

    total = sum(components.values())
    return {"total": round(total, 2), "components": components}
