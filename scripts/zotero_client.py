"""Zotero Web API 客户端"""

import logging
from typing import Optional

import requests

from scripts.config import ZOTERO_USER_ID, ZOTERO_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://api.zotero.org"


class ZoteroClient:
    """Zotero Web API 客户端"""

    def __init__(
        self,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.user_id = user_id or ZOTERO_USER_ID
        self.api_key = api_key or ZOTERO_API_KEY

        if not self.user_id or not self.api_key:
            raise ValueError(
                "ZOTERO_USER_ID 和 ZOTERO_API_KEY 未设置，请在 .env 文件中配置"
            )

        self.session = requests.Session()
        self.session.headers.update({
            "Zotero-API-Key": self.api_key,
            "Zotero-API-Version": "3",
        })

    def get_collections(self, filter_names: list[str] = None) -> list[dict]:
        """获取集合列表，自动展开父集合为子集合。

        Args:
            filter_names: 指定集合名列表（支持任意层级）。为空时返回所有顶层集合。

        Returns:
            集合列表，每项包含 key 和 data.name
        """
        all_collections = []
        start = 0
        while True:
            resp = self.session.get(
                f"{BASE_URL}/users/{self.user_id}/collections",
                params={"limit": 100, "start": start},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_collections.extend(batch)
            start += len(batch)
            if len(batch) < 100:
                break

        # 建立 key → collection 和 parent → children 索引
        by_key = {c["key"]: c for c in all_collections}
        children_map: dict[str, list[dict]] = {}
        for c in all_collections:
            parent = c.get("data", {}).get("parentCollection", "")
            if parent:
                children_map.setdefault(parent, []).append(c)

        def get_leaf_collections(col_key: str) -> list[dict]:
            """递归获取叶子集合（无子集合的集合）"""
            kids = children_map.get(col_key, [])
            if not kids:
                return [by_key[col_key]]
            result = []
            for kid in kids:
                result.extend(get_leaf_collections(kid["key"]))
            return result

        top_level = [
            c for c in all_collections
            if not c.get("data", {}).get("parentCollection")
        ]

        if filter_names:
            # 按名称搜索所有集合（不限层级）
            name_index: dict[str, dict] = {}
            for c in all_collections:
                name_index[c["data"]["name"]] = c

            result = []
            for fname in filter_names:
                col = name_index.get(fname)
                if not col:
                    logger.warning(f"Zotero 集合 '{fname}' 未找到")
                    continue
                leaves = get_leaf_collections(col["key"])
                for leaf in leaves:
                    leaf["_matched_parent"] = fname
                result.extend(leaves)
            return result

        return top_level

    def get_collection_items(self, collection_key: str) -> list[dict]:
        """获取集合中所有条目（排除附件和笔记）"""
        items = []
        start = 0
        while True:
            resp = self.session.get(
                f"{BASE_URL}/users/{self.user_id}/collections/{collection_key}/items",
                params={
                    "itemType": "journalArticle || conferencePaper || preprint || book || bookSection || report || thesis || manuscript || patent",
                    "limit": 100,
                    "start": start,
                },
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            items.extend(batch)
            start += len(batch)
            if len(batch) < 100:
                break
        return items

    def extract_dois(self, items: list[dict]) -> list[str]:
        """从 Zotero 条目中提取 DOI 列表"""
        dois = []
        for item in items:
            data = item.get("data", {})
            doi = (data.get("DOI") or "").strip()
            if not doi:
                url = data.get("url") or ""
                if "doi.org/" in url:
                    doi = url.split("doi.org/", 1)[1].strip()
            if doi:
                dois.append(doi.lower())
        return dois
