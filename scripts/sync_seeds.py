"""种子同步模块 — 从 Zotero 同步 DOI 到 seed_dois.json"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from scripts.config import SEED_DOIS_FILE, ZOTERO_COLLECTIONS
from scripts.zotero_client import ZoteroClient

logger = logging.getLogger(__name__)


def load_seeds(path: Path = None) -> list[dict]:
    """加载 seed_dois.json，自动适配旧格式"""
    path = path or SEED_DOIS_FILE
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = []
    for entry in data:
        if isinstance(entry, str):
            entry = {"doi": entry}
        result.append({
            "doi": entry.get("doi", ""),
            "zotero_collections": entry.get("zotero_collections", []),
            "synced_at": entry.get("synced_at", ""),
        })
    return result


def save_seeds(seeds: list[dict], path: Path = None):
    """保存 seed_dois.json"""
    path = path or SEED_DOIS_FILE
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seeds, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存 {len(seeds)} 个种子 DOI 到 {path}")


def merge_dois(
    existing: list[dict],
    new_dois: dict[str, list[str]],
    sync_date: str = "",
) -> list[dict]:
    """将新发现的 DOI 合并到现有种子列表。

    Args:
        existing: 现有种子列表
        new_dois: {doi: [collection_name, ...]}
        sync_date: 同步时间戳

    Returns:
        合并后的种子列表
    """
    doi_index: dict[str, dict] = {}
    for entry in existing:
        doi_index[entry["doi"]] = entry

    added = 0
    updated = 0

    for doi, collections in new_dois.items():
        if doi in doi_index:
            old_cols = set(doi_index[doi].get("zotero_collections", []))
            new_cols = set(collections)
            merged = sorted(old_cols | new_cols)
            if merged != sorted(old_cols):
                doi_index[doi]["zotero_collections"] = merged
                updated += 1
        else:
            doi_index[doi] = {
                "doi": doi,
                "zotero_collections": sorted(collections),
                "synced_at": sync_date,
            }
            added += 1

    if added or updated:
        logger.info(f"种子同步: 新增 {added}, 更新集合归属 {updated}")

    return list(doi_index.values())


def sync_from_zotero(seeds_path: Path = None) -> int:
    """从 Zotero 同步种子 DOI。

    Returns:
        新增的种子数量
    """
    seeds_path = seeds_path or SEED_DOIS_FILE

    from scripts.config import ZOTERO_USER_ID, ZOTERO_API_KEY
    if not ZOTERO_USER_ID or not ZOTERO_API_KEY:
        logger.warning("Zotero 未配置，跳过种子同步")
        return 0

    client = ZoteroClient()

    filter_names = []
    if ZOTERO_COLLECTIONS:
        filter_names = [n.strip() for n in ZOTERO_COLLECTIONS.split(",") if n.strip()]

    collections = client.get_collections(filter_names=filter_names)
    if not collections:
        logger.warning("未找到匹配的 Zotero 集合")
        return 0

    logger.info(f"找到 {len(collections)} 个 Zotero 集合: {[c['data']['name'] for c in collections]}")

    doi_to_collections: dict[str, list[str]] = {}
    for col in collections:
        col_name = col.get("_matched_parent", col["data"]["name"])
        col_key = col["key"]
        items = client.get_collection_items(col_key)
        dois = client.extract_dois(items)
        logger.info(f"  集合 '{col_name}': {len(items)} 条目, {len(dois)} 个 DOI")

        for doi in dois:
            if doi not in doi_to_collections:
                doi_to_collections[doi] = []
            if col_name not in doi_to_collections[doi]:
                doi_to_collections[doi].append(col_name)

    existing = load_seeds(seeds_path)
    old_count = len(existing)
    sync_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    merged = merge_dois(existing, doi_to_collections, sync_date)
    save_seeds(merged, seeds_path)

    new_count = len(merged) - old_count
    logger.info(f"种子同步完成: {old_count} → {len(merged)} (新增 {new_count})")
    return new_count
