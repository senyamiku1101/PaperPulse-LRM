"""论文发现模块 — 从种子 DOI 发现候选论文"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

from scripts.config import DATA_DIR, SEED_DOIS_FILE, CITATION_CONFIG
from scripts.data_models import empty_candidates, save_json
from scripts.openalex_client import OpenAlexClient

logger = logging.getLogger(__name__)

CANDIDATES_FILE = DATA_DIR / "candidates.json"
PAPERS_FILE = DATA_DIR / "papers.json"
FETCH_WORKERS = 4


def load_candidates() -> dict:
    """加载 candidates.json，不存在则返回空结构"""
    if CANDIDATES_FILE.exists():
        with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return empty_candidates()


def save_candidates(data: dict):
    """保存 candidates.json"""
    save_json(data, CANDIDATES_FILE)
    logger.info(f"已保存 {len(data['candidates'])} 个候选到 {CANDIDATES_FILE}")


def load_existing_papers() -> dict:
    """加载已有的 papers.json（兼容旧逻辑）"""
    if PAPERS_FILE.exists():
        with open(PAPERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_updated": "", "total_count": 0, "papers": []}


def save_papers(data: dict):
    """保存 papers.json（兼容旧逻辑）"""
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["total_count"] = len(data["papers"])
    with open(PAPERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存 {data['total_count']} 篇论文到 {PAPERS_FILE}")


def load_seed_dois() -> list[dict]:
    """加载种子 DOI 列表，兼容新旧两种格式"""
    if not SEED_DOIS_FILE.exists():
        logger.warning(f"种子 DOI 文件不存在: {SEED_DOIS_FILE}")
        return []
    with open(SEED_DOIS_FILE, "r", encoding="utf-8") as f:
        seeds = json.load(f)
    if not seeds:
        logger.warning("种子 DOI 文件为空")
    result = []
    for s in seeds:
        if isinstance(s, str):
            result.append({"doi": s})
        elif isinstance(s, dict):
            result.append(s)
    return result


def _fetch_seed_citers(
    seed_entry: dict,
    candidate_index: dict,
    index_lock: threading.Lock,
    existing_ids: set,
):
    """获取单个种子的引用者（仅最近 1 年），供线程池调用"""
    doi = seed_entry.get("doi", "")
    label = seed_entry.get("label", doi)
    client = OpenAlexClient()
    local_new = 0
    current_year = datetime.now().year
    cutoff_year = current_year - 1

    logger.info(f"获取种子引用者: {label}")

    raw_seed = client.get_work_by_doi(doi)
    if not raw_seed:
        logger.error(f"无法获取种子论文: {doi}")
        return doi, 0

    seed_paper = OpenAlexClient.extract_paper(raw_seed, discovery_origin="seed", seed_doi=doi)
    seed_id = seed_paper["id"]
    clean_doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

    with index_lock:
        if seed_id and seed_id not in candidate_index and seed_id not in existing_ids:
            candidate_index[seed_id] = {
                "id": seed_id,
                "doi": clean_doi,
                "title": seed_paper.get("title", ""),
                "abstract": seed_paper.get("abstract", ""),
                "year": seed_paper.get("year"),
                "topics": seed_paper.get("topics", []),
                "source": seed_paper.get("source", {}),
                "discovered_via": "seed",
                "seed_connections": [clean_doi],
            }
            local_new += 1

    if seed_id:
        citing_results = client.get_citing_works(
            seed_id,
            max_results=CITATION_CONFIG.get("max_citers_per_seed", 50),
        )
        citing_count = 0
        with index_lock:
            for raw in citing_results:
                paper = OpenAlexClient.extract_paper(raw, discovery_origin="citing", seed_doi=clean_doi)
                pid = paper["id"]
                paper_year = paper.get("year")
                # 只保留最近 1 年的引用者
                if paper_year and paper_year < cutoff_year:
                    continue
                if pid and pid not in candidate_index and pid not in existing_ids:
                    candidate_index[pid] = {
                        "id": pid,
                        "doi": (paper.get("doi") or "").replace("https://doi.org/", ""),
                        "title": paper.get("title", ""),
                        "abstract": paper.get("abstract", ""),
                        "year": paper.get("year"),
                        "topics": paper.get("topics", []),
                        "source": paper.get("source", {}),
                        "discovered_via": "citing_seed",
                        "seed_connections": [clean_doi],
                    }
                    local_new += 1
                    citing_count += 1
                elif pid in candidate_index:
                    if clean_doi not in candidate_index[pid]["seed_connections"]:
                        candidate_index[pid]["seed_connections"].append(clean_doi)
        logger.info(f"  引用者: 获取 {len(citing_results)} 篇, 新增 {citing_count} 篇")

    return doi, local_new


def fetch_candidates():
    """从种子 DOI 发现候选论文，写入 candidates.json"""
    existing_candidates = load_candidates()
    candidate_index = {}
    for c in existing_candidates.get("candidates", []):
        candidate_index[c["id"]] = c

    existing_papers = load_existing_papers()
    existing_ids = {p["id"] for p in existing_papers.get("papers", [])}

    seeds = load_seed_dois()
    if not seeds:
        logger.warning("没有种子 DOI，跳过候选发现")
        return

    logger.info(f"已有 {len(candidate_index)} 个候选, {len(existing_ids)} 篇已入库论文")
    logger.info(f"开始处理 {len(seeds)} 个种子 DOI（{FETCH_WORKERS} 并发）...")

    index_lock = threading.Lock()
    total_new = 0

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_seed_citers, seed, candidate_index, index_lock, existing_ids): seed.get("doi", "")
            for seed in seeds
        }
        for future in as_completed(futures):
            doi = futures[future]
            try:
                _, new = future.result()
                total_new += new
            except Exception as e:
                logger.error(f"种子 {doi} 处理异常: {e}")

    candidates_list = sorted(
        candidate_index.values(),
        key=lambda c: (c.get("year") or 0),
        reverse=True,
    )

    save_candidates({"candidates": candidates_list})
    logger.info(f"候选发现完成，新增 {total_new} 个，总计 {len(candidates_list)} 个")


def fetch_citation_graph():
    """兼容旧接口，内部调用 fetch_candidates"""
    fetch_candidates()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetch_candidates()
