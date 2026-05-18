"""问题图谱初始化模块 — 从种子论文聚类为研究问题"""

import json
import logging
import re
from datetime import datetime, timezone

from scripts.config import DATA_DIR, SEED_DOIS_FILE
from scripts.data_models import empty_questions, save_json
from scripts.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

QUESTIONS_FILE = DATA_DIR / "questions.json"
PAPERS_FILE = DATA_DIR / "papers.json"


def build_seed_info_text(
    seeds: list[dict],
    papers_by_doi: dict[str, dict],
) -> str:
    """将种子论文信息按 Zotero 集合分组格式化为文本"""
    collection_groups: dict[str, list[dict]] = {}
    for seed in seeds:
        doi = seed.get("doi", "")
        collections = seed.get("zotero_collections", [])
        paper_info = papers_by_doi.get(doi, {})
        title = paper_info.get("title", doi)
        abstract = (paper_info.get("abstract", "") or "")[:200]

        if not collections:
            collections = ["未分类"]

        for col in collections:
            if col not in collection_groups:
                collection_groups[col] = []
            collection_groups[col].append({
                "doi": doi,
                "title": title,
                "abstract": abstract,
            })

    lines = []
    for col_name, papers in collection_groups.items():
        lines.append(f"\n## 集合: {col_name}")
        for p in papers:
            line = f"- DOI: {p['doi']}"
            if p["title"]:
                line += f"\n  标题: {p['title']}"
            if p["abstract"]:
                line += f"\n  摘要: {p['abstract']}..."
            lines.append(line)

    return "\n".join(lines)


def parse_questions_response(response_text: str) -> list[dict]:
    """解析 DeepSeek 返回的问题 JSON"""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", response_text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
        else:
            raise ValueError(f"无法解析 DeepSeek 返回: {response_text[:200]}")

    questions = data.get("questions", [])
    result = []
    seen_ids = set()

    for q in questions:
        name = q.get("name", "")
        base_id = re.sub(r"[^a-zA-Z0-9一-鿿]", "_", name).strip("_").lower()
        if not base_id:
            base_id = f"q_{len(result) + 1}"
        qid = f"q_{base_id}"
        if qid in seen_ids:
            qid = f"{qid}_{len(result) + 1}"
        seen_ids.add(qid)

        result.append({
            "id": qid,
            "name": name,
            "description": q.get("description", ""),
            "seed_dois": q.get("seed_dois", []),
            "keywords": q.get("keywords", []),
            "methods_of_interest": q.get("methods_of_interest", []),
            "status": "active",
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "evidence_count": 0,
            "gap_flags": [],
        })

    return result


def init_questions(force: bool = False):
    """初始化问题图谱"""
    if QUESTIONS_FILE.exists() and not force:
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("questions"):
            logger.info(f"问题图谱已存在（{len(data['questions'])} 个问题），跳过初始化。使用 --init-questions 强制重建。")
            return

    if not SEED_DOIS_FILE.exists():
        logger.error("seed_dois.json 不存在，无法初始化问题图谱")
        return

    with open(SEED_DOIS_FILE, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    if not seeds:
        logger.warning("种子列表为空")
        return

    papers_by_doi = {}
    if PAPERS_FILE.exists():
        with open(PAPERS_FILE, "r", encoding="utf-8") as f:
            papers_data = json.load(f)
        for p in papers_data.get("papers", []):
            doi = (p.get("doi") or "").replace("https://doi.org/", "").lower()
            if doi:
                papers_by_doi[doi] = {"title": p.get("title", ""), "abstract": p.get("abstract", "")}

    from scripts.openalex_client import OpenAlexClient
    client_oa = OpenAlexClient()
    missing = []
    for seed in seeds:
        doi = seed.get("doi", "")
        clean_doi = doi.replace("https://doi.org/", "").lower()
        if clean_doi not in papers_by_doi:
            missing.append((doi, clean_doi))

    if missing:
        logger.info(f"需要从 OpenAlex 获取 {len(missing)} 篇种子论文信息...")
        for doi, clean_doi in missing:
            raw = client_oa.get_work_by_doi(doi)
            if raw:
                paper = OpenAlexClient.extract_paper(raw)
                papers_by_doi[clean_doi] = {
                    "title": paper.get("title", ""),
                    "abstract": paper.get("abstract", ""),
                }

    # 只包含有标题信息的种子
    seeds_with_info = [s for s in seeds if papers_by_doi.get(s.get("doi", "").replace("https://doi.org/", "").lower(), {}).get("title")]
    if len(seeds_with_info) < 3:
        logger.warning(f"仅有 {len(seeds_with_info)} 篇种子有标题信息，无法聚类")
        return

    seed_text = build_seed_info_text(seeds_with_info, papers_by_doi)

    logger.info(f"调用 DeepSeek 聚类 {len(seeds_with_info)} 篇种子论文（共 {len(seeds)} 篇，{len(seeds_with_info)} 篇有标题）...")
    ds_client = DeepSeekClient()
    response = ds_client.cluster_questions(seed_text)
    questions = parse_questions_response(response)

    data = empty_questions()
    data["questions"] = questions
    save_json(data, QUESTIONS_FILE)

    logger.info(f"问题图谱初始化完成: {len(questions)} 个问题")
    for q in questions:
        logger.info(f"  - {q['id']}: {q['name']} ({len(q['seed_dois'])} 篇种子)")
