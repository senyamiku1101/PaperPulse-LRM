"""候选提升模块 — 从候选池中筛选并提升 top N 到论文库"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

from scripts.config import DATA_DIR
from scripts.data_models import new_paper_entry, save_json
from scripts.scoring import score_candidate

logger = logging.getLogger(__name__)

CANDIDATES_FILE = DATA_DIR / "candidates.json"
PAPERS_FILE = DATA_DIR / "papers.json"

DEFAULT_THRESHOLD = 5.0
DEFAULT_PER_QUESTION_LIMIT = 5
DEFAULT_GLOBAL_LIMIT = 30


def score_and_rank_candidates(
    candidates: list[dict],
    questions: list[dict],
    negative_keywords: list[str] = None,
) -> list[dict]:
    """对所有候选论文评分并排序。"""
    scored = []

    for candidate in candidates:
        best_score = {"total": 0, "components": {}}
        best_question_id = ""

        for question in questions:
            result = score_candidate(
                paper=candidate,
                question=question,
                seed_connections=candidate.get("seed_connections", []),
                negative_keywords=negative_keywords,
            )
            if result["total"] > best_score["total"]:
                best_score = result
                best_question_id = question["id"]

        candidate["scores"] = best_score
        candidate["best_question"] = best_question_id
        scored.append(candidate)

    scored.sort(key=lambda c: c["scores"]["total"], reverse=True)
    return scored


def promote_top_n(
    scored_candidates: list[dict],
    threshold: float = DEFAULT_THRESHOLD,
    per_question_limit: int = DEFAULT_PER_QUESTION_LIMIT,
    global_limit: int = DEFAULT_GLOBAL_LIMIT,
) -> list[dict]:
    """从已评分候选中提升 top N 为 promoted 论文。"""
    promoted = []
    per_question_count = defaultdict(int)

    for candidate in scored_candidates:
        if candidate.get("promoted"):
            continue
        if candidate["scores"]["total"] < threshold:
            continue
        best_q = candidate.get("best_question", "")
        if per_question_count[best_q] >= per_question_limit:
            continue
        if len(promoted) >= global_limit:
            break
        candidate["promoted"] = True
        promoted.append(candidate)
        per_question_count[best_q] += 1

    return promoted


def run_promotion() -> int:
    """执行候选提升流程。"""
    if not CANDIDATES_FILE.exists():
        logger.warning("candidates.json 不存在，跳过提升")
        return 0

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        candidates_data = json.load(f)
    candidates = candidates_data.get("candidates", [])

    questions_file = DATA_DIR / "questions.json"
    if questions_file.exists():
        with open(questions_file, "r", encoding="utf-8") as f:
            questions_data = json.load(f)
        questions = questions_data.get("questions", [])
    else:
        questions = [{"id": "_default", "keywords": [], "seed_dois": [], "methods_of_interest": []}]

    scored = score_and_rank_candidates(candidates, questions)
    promoted = promote_top_n(scored)

    if not promoted:
        logger.info("没有候选达到提升阈值")
        candidates_data["candidates"] = scored
        save_json(candidates_data, CANDIDATES_FILE)
        return 0

    if PAPERS_FILE.exists():
        with open(PAPERS_FILE, "r", encoding="utf-8") as f:
            papers_data = json.load(f)
    else:
        papers_data = {"last_updated": "", "total_count": 0, "papers": []}

    existing_ids = {p["id"] for p in papers_data["papers"]}

    added = 0
    for cand in promoted:
        if cand["id"] in existing_ids:
            continue
        paper = new_paper_entry(
            id=cand["id"],
            doi=cand.get("doi", ""),
            title=cand.get("title", ""),
            year=cand.get("year"),
            abstract=cand.get("abstract", ""),
            role="promoted",
        )
        paper["question_ids"] = [cand.get("best_question", "")]
        paper["scores"] = cand.get("scores", {})
        paper["discovery_reason"] = f"via {cand.get('discovered_via', 'unknown')}, connections: {len(cand.get('seed_connections', []))}"
        papers_data["papers"].append(paper)
        added += 1

    save_json(papers_data, PAPERS_FILE)

    candidates_data["candidates"] = scored
    save_json(candidates_data, CANDIDATES_FILE)

    logger.info(f"提升完成: {added} 篇候选提升为论文, 总计 {len(papers_data['papers'])} 篇")
    return added
