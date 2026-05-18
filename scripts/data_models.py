"""数据模型辅助函数 — 定义各 JSON 文件的空结构和加载逻辑"""

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.config import DATA_DIR


def empty_candidates() -> dict:
    return {"candidates": [], "last_updated": ""}


def empty_questions() -> dict:
    return {"questions": [], "last_updated": ""}


def empty_claims() -> dict:
    return {"claims": [], "last_updated": ""}


def empty_frontier() -> dict:
    return {
        "week": "",
        "generated_at": "",
        "changes": [],
        "top_papers": [],
        "model_diff_summary": "",
    }


_EMPTY_MAP = {
    "candidates": empty_candidates,
    "questions": empty_questions,
    "claims": empty_claims,
    "frontier": empty_frontier,
}


def load_or_create(path: Path, schema_type: str) -> dict:
    """加载 JSON 文件，不存在则创建空结构"""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    factory = _EMPTY_MAP.get(schema_type)
    if not factory:
        raise ValueError(f"未知 schema 类型: {schema_type}")

    data = factory()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return data


def save_json(data: dict, path: Path):
    """保存 JSON 并更新 last_updated"""
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def new_paper_entry(
    id: str,
    doi: str = "",
    title: str = "",
    year: int = None,
    abstract: str = "",
    role: str = "candidate",
) -> dict:
    """创建新论文条目"""
    return {
        "id": id,
        "doi": doi,
        "title": title,
        "year": year,
        "abstract": abstract,
        "authors": [],
        "topics": [],
        "source": {},
        "role": role,
        "question_ids": [],
        "claim_ids": [],
        "discovery_reason": "",
        "scores": {"total": 0, "components": {}},
        "analysis": None,
    }
