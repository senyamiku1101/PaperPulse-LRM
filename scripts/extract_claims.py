"""结构化主张提取模块"""

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from scripts.config import DATA_DIR
from scripts.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

PAPERS_FILE = DATA_DIR / "papers.json"
CLAIMS_FILE = DATA_DIR / "claims.json"
QUESTIONS_FILE = DATA_DIR / "questions.json"
EXTRACT_WORKERS = 5
SAVE_INTERVAL = 10


def parse_claims_response(
    response_text: str,
    paper_id: str = "",
    question_id: str = "",
) -> dict:
    """解析 DeepSeek 返回的主张 JSON"""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", response_text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
        else:
            raise ValueError(f"无法解析主张 JSON: {response_text[:200]}")

    claims = data.get("claims", [])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    result_claims = []
    for i, claim in enumerate(claims):
        cid = f"claim_{paper_id}_{i + 1}" if paper_id else f"claim_{now}_{i + 1}"
        result_claims.append({
            "id": cid,
            "question_id": question_id,
            "statement": claim.get("statement", ""),
            "method": claim.get("method", ""),
            "evidence_type": claim.get("evidence_type", ""),
            "geometry": claim.get("geometry", ""),
            "condition": claim.get("condition", ""),
            "outcome": claim.get("outcome", ""),
            "limitation": claim.get("limitation", ""),
            "supporting_papers": [paper_id] if paper_id else [],
            "contradicting_papers": [],
            "confidence": "moderate",
            "created_at": now,
        })

    return {
        "claims": result_claims,
        "relevance_to_question": data.get("relevance_to_question", 0),
        "novelty": data.get("novelty", "unknown"),
        "question_affinity": data.get("question_affinity", []),
    }


def extract_claims_for_papers(force: bool = False):
    """对 papers.json 中未提取主张的 promoted 论文执行主张提取"""
    if not PAPERS_FILE.exists():
        logger.warning("papers.json 不存在")
        return

    with open(PAPERS_FILE, "r", encoding="utf-8") as f:
        papers_data = json.load(f)
    papers = papers_data.get("papers", [])

    questions_map = {}
    if QUESTIONS_FILE.exists():
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            for q in json.load(f).get("questions", []):
                questions_map[q["id"]] = q

    if CLAIMS_FILE.exists():
        with open(CLAIMS_FILE, "r", encoding="utf-8") as f:
            claims_data = json.load(f)
    else:
        claims_data = {"claims": [], "last_updated": ""}

    existing_claim_ids = {c["id"] for c in claims_data["claims"]}

    to_extract = []
    for p in papers:
        if p.get("role") not in ("seed", "promoted"):
            continue
        if p.get("analysis") is not None and not force:
            if not p.get("claim_ids"):
                to_extract.append(p)
            continue
        if not p.get("abstract", "").strip():
            continue
        to_extract.append(p)

    if not to_extract:
        logger.info("没有待提取主张的论文")
        return

    logger.info(f"待提取主张: {len(to_extract)} 篇论文（{EXTRACT_WORKERS} 并发）")

    client = DeepSeekClient()
    counter_lock = threading.Lock()
    progress = [0]
    new_claims = []

    def _extract_one(idx, paper):
        qids = paper.get("question_ids", [])
        qid = qids[0] if qids else ""
        q_name = ""
        if qids:
            q = questions_map.get(qids[0], {})
            q_name = q.get("name", "")

        raw_result = client.extract_claims(
            title=paper.get("title", ""),
            abstract=paper.get("abstract", ""),
            question_name=q_name,
        )

        parsed = parse_claims_response(
            json.dumps(raw_result),
            paper_id=paper.get("id", ""),
            question_id=qid,
        )

        paper["analysis"] = {
            "claims_summary": raw_result,
            "relevance_to_question": parsed.get("relevance_to_question", 0),
            "novelty": parsed.get("novelty", "unknown"),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        claim_ids = []
        for claim in parsed.get("claims", []):
            if claim["id"] not in existing_claim_ids:
                new_claims.append(claim)
                existing_claim_ids.add(claim["id"])
            claim_ids.append(claim["id"])

        paper["claim_ids"] = claim_ids

        with counter_lock:
            progress[0] += 1
            logger.info(f"主张提取 [{progress[0]}/{len(to_extract)}]: {paper.get('title', '')[:50]}...")

    with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as executor:
        futures = {
            executor.submit(_extract_one, i, p): p
            for i, p in enumerate(to_extract)
        }
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"主张提取异常: {e}")

    claims_data["claims"].extend(new_claims)
    claims_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(CLAIMS_FILE, "w", encoding="utf-8") as f:
        json.dump(claims_data, f, ensure_ascii=False, indent=2)

    papers_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(PAPERS_FILE, "w", encoding="utf-8") as f:
        json.dump(papers_data, f, ensure_ascii=False, indent=2)

    logger.info(f"主张提取完成: {len(new_claims)} 条新主张, 总计 {len(claims_data['claims'])} 条")
