# PaperPulse 活的研究前沿模型 — 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 PaperPulse 从"论文追踪器"重构为"研究前沿的活模型"，以研究问题为核心，通过廉价筛选漏斗控制 AI 调用预算。

**Architecture:** 种子论文从 Zotero 同步 → 候选发现 → 廉价评分筛选 → 结构化主张提取 → 问题状态更新 → 前沿差异生成。数据模型从单一 papers.json 扩展为 questions/claims/candidates/papers/frontier 五文件体系。

**Tech Stack:** Python 3.12+, OpenAlex API, Zotero Web API, DeepSeek API (OpenAI compatible), pytest, 纯 HTML/CSS/JS 前端

**Design doc:** `docs/plans/2026-05-18-living-research-model-design.md`

---

## Phase 0: 基础设施

### Task 1: Zotero API 客户端

**Files:**
- Create: `scripts/zotero_client.py`
- Create: `tests/test_zotero_client.py`
- Modify: `scripts/config.py`

**Step 1: 写 config.py 的 Zotero 配置**

在 `scripts/config.py` 末尾 `YEAR_RANGES = get_year_ranges()` 之后追加：

```python
# Zotero API
ZOTERO_USER_ID = os.getenv("ZOTERO_USER_ID", "")
ZOTERO_API_KEY = os.getenv("ZOTERO_API_KEY", "")
ZOTERO_COLLECTIONS = os.getenv("ZOTERO_COLLECTIONS", "")
# 格式: "集合名1,集合名2" 或留空表示全部
```

**Step 2: 写 Zotero 客户端的失败测试**

创建 `tests/test_zotero_client.py`：

```python
"""Zotero API 客户端测试"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestZoteroClient:
    def test_init_requires_credentials(self):
        """缺少凭据应抛出 ValueError"""
        from scripts.zotero_client import ZoteroClient
        with pytest.raises(ValueError, match="ZOTERO"):
            ZoteroClient(user_id="", api_key="")

    def test_init_with_credentials(self):
        from scripts.zotero_client import ZoteroClient
        client = ZoteroClient(user_id="12345", api_key="test-key")
        assert client.user_id == "12345"
        assert client.session is not None

    def test_extract_doi_from_field(self):
        from scripts.zotero_client import ZoteroClient
        client = ZoteroClient(user_id="12345", api_key="test-key")
        items = [
            {"data": {"DOI": "10.1234/test", "itemType": "journalArticle"}},
            {"data": {"DOI": "", "url": "https://doi.org/10.5678/other", "itemType": "journalArticle"}},
            {"data": {"DOI": "", "url": "", "itemType": "attachment"}},
        ]
        dois = client.extract_dois(items)
        assert "10.1234/test" in dois
        assert "10.5678/other" in dois
        assert len(dois) == 2

    def test_extract_doi_normalizes(self):
        """DOI 应被小写并去除空白"""
        from scripts.zotero_client import ZoteroClient
        client = ZoteroClient(user_id="12345", api_key="test-key")
        items = [{"data": {"DOI": " 10.1234/TEST ", "itemType": "journalArticle"}}]
        dois = client.extract_dois(items)
        assert dois == ["10.1234/test"]

    def test_get_collections_parses_names(self):
        from scripts.zotero_client import ZoteroClient
        client = ZoteroClient(user_id="12345", api_key="test-key")
        # Mock API response
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"key": "ABC123", "data": {"name": "宽频噪声", "parentCollection": False}},
            {"key": "DEF456", "data": {"name": "声衬设计", "parentCollection": False}},
            {"key": "GHI789", "data": {"name": "子集合", "parentCollection": "ABC123"}},
        ]
        mock_resp.raise_for_status = MagicMock()
        client.session.get = MagicMock(return_value=mock_resp)

        cols = client.get_collections(filter_names=["宽频噪声"])
        assert len(cols) == 1
        assert cols[0]["key"] == "ABC123"

    def test_get_collections_all_top_level(self):
        """filter_names 为空时返回所有顶层集合"""
        from scripts.zotero_client import ZoteroClient
        client = ZoteroClient(user_id="12345", api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"key": "ABC123", "data": {"name": "宽频噪声", "parentCollection": False}},
            {"key": "DEF456", "data": {"name": "声衬设计", "parentCollection": False}},
            {"key": "GHI789", "data": {"name": "子集合", "parentCollection": "ABC123"}},
        ]
        mock_resp.raise_for_status = MagicMock()
        client.session.get = MagicMock(return_value=mock_resp)

        cols = client.get_collections(filter_names=[])
        # 应只返回顶层集合（parentCollection 为 False）
        assert len(cols) == 2
```

**Step 3: 运行测试确认失败**

Run: `pytest tests/test_zotero_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.zotero_client'`

**Step 4: 实现 ZoteroClient**

创建 `scripts/zotero_client.py`：

```python
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
        """获取集合列表。

        Args:
            filter_names: 指定集合名列表。为空时返回所有顶层集合。

        Returns:
            集合列表，每项包含 key 和 data.name
        """
        resp = self.session.get(f"{BASE_URL}/users/{self.user_id}/collections")
        resp.raise_for_status()
        all_collections = resp.json()

        # 过滤：只要顶层集合（parentCollection 为 False 或空字符串）
        top_level = [
            c for c in all_collections
            if not c.get("data", {}).get("parentCollection")
        ]

        if filter_names:
            return [c for c in top_level if c["data"]["name"] in filter_names]

        return top_level

    def get_collection_items(self, collection_key: str) -> list[dict]:
        """获取集合中所有条目（排除附件和笔记）"""
        items = []
        start = 0
        while True:
            resp = self.session.get(
                f"{BASE_URL}/users/{self.user_id}/collections/{collection_key}/items",
                params={
                    "itemType": "-attachment || -note",
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
```

**Step 5: 运行测试确认通过**

Run: `pytest tests/test_zotero_client.py -v`
Expected: 全部 PASS

**Step 6: Commit**

```bash
git add scripts/zotero_client.py scripts/config.py tests/test_zotero_client.py
git commit -m "feat: add Zotero Web API client with collection/item fetching"
```

---

### Task 2: 种子同步模块

**Files:**
- Create: `scripts/sync_seeds.py`
- Create: `tests/test_sync_seeds.py`

**Step 1: 写失败测试**

创建 `tests/test_sync_seeds.py`：

```python
"""种子同步模块测试"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestSyncSeeds:
    def test_merge_new_dois(self):
        """新增 DOI 应追加到种子列表"""
        from scripts.sync_seeds import merge_dois

        existing = [
            {"doi": "10.1234/a", "zotero_collections": ["col1"], "synced_at": "2026-01-01"},
        ]
        new_dois = {"10.1234/a": ["col1"], "10.5678/b": ["col2"]}

        result = merge_dois(existing, new_dois, sync_date="2026-05-18")
        assert len(result) == 2
        # 已存在的应更新 zotero_collections
        a_entry = next(e for e in result if e["doi"] == "10.1234/a")
        assert a_entry["zotero_collections"] == ["col1"]
        # 新增的应被添加
        b_entry = next(e for e in result if e["doi"] == "10.5678/b")
        assert b_entry["zotero_collections"] == ["col2"]
        assert b_entry["synced_at"] == "2026-05-18"

    def test_merge_deduplicates(self):
        """同一 DOI 出现在多个集合中应合并集合列表"""
        from scripts.sync_seeds import merge_dois

        existing = []
        new_dois = {"10.1234/a": ["col1"], "10.1234/a": ["col2"]}
        # dict key 去重，实际只会有 col2
        # 测试显式传入合并场景
        new_dois_multi = {"10.1234/a": ["col1", "col2"]}
        result = merge_dois(existing, new_dois_multi, sync_date="2026-05-18")
        assert len(result) == 1
        assert set(result[0]["zotero_collections"]) == {"col1", "col2"}

    def test_merge_preserves_manual_seeds(self):
        """手动添加的种子（无 zotero_collections）应保留"""
        from scripts.sync_seeds import merge_dois

        existing = [
            {"doi": "10.manual/seed", "zotero_collections": [], "synced_at": ""},
        ]
        new_dois = {"10.1234/a": ["col1"]}

        result = merge_dois(existing, new_dois, sync_date="2026-05-18")
        assert len(result) == 2
        manual = next(e for e in result if e["doi"] == "10.manual/seed")
        assert manual["zotero_collections"] == []

    def test_load_legacy_format(self):
        """旧格式 seed_dois.json 应自动适配"""
        from scripts.sync_seeds import load_seeds

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            json.dump([{"doi": "10.1234/a"}, {"doi": "10.5678/b"}], f)
            tmp_path = f.name

        try:
            result = load_seeds(Path(tmp_path))
            assert len(result) == 2
            assert result[0]["zotero_collections"] == []
            assert result[0]["doi"] == "10.1234/a"
        finally:
            Path(tmp_path).unlink()

    def test_load_new_format(self):
        """新格式应直接加载"""
        from scripts.sync_seeds import load_seeds

        data = [{"doi": "10.1234/a", "zotero_collections": ["col1"], "synced_at": "2026-05-18"}]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            result = load_seeds(Path(tmp_path))
            assert len(result) == 1
            assert result[0]["zotero_collections"] == ["col1"]
        finally:
            Path(tmp_path).unlink()
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_sync_seeds.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: 实现 sync_seeds.py**

创建 `scripts/sync_seeds.py`：

```python
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

    # 适配旧格式：[{"doi": "..."}] → 补充缺失字段
    result = []
    for entry in data:
        if isinstance(entry, str):
            # 极旧格式：纯 DOI 字符串列表
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
    # 建立 doi → entry 索引
    doi_index: dict[str, dict] = {}
    for entry in existing:
        doi_index[entry["doi"]] = entry

    added = 0
    updated = 0

    for doi, collections in new_dois.items():
        if doi in doi_index:
            # 已存在：合并集合列表
            old_cols = set(doi_index[doi].get("zotero_collections", []))
            new_cols = set(collections)
            merged = sorted(old_cols | new_cols)
            if merged != sorted(old_cols):
                doi_index[doi]["zotero_collections"] = merged
                updated += 1
        else:
            # 新增
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

    # 检查 Zotero 配置
    from scripts.config import ZOTERO_USER_ID, ZOTERO_API_KEY
    if not ZOTERO_USER_ID or not ZOTERO_API_KEY:
        logger.warning("Zotero 未配置，跳过种子同步")
        return 0

    client = ZoteroClient()

    # 解析要监听的集合名
    filter_names = []
    if ZOTERO_COLLECTIONS:
        filter_names = [n.strip() for n in ZOTERO_COLLECTIONS.split(",") if n.strip()]

    # 获取集合
    collections = client.get_collections(filter_names=filter_names)
    if not collections:
        logger.warning("未找到匹配的 Zotero 集合")
        return 0

    logger.info(f"找到 {len(collections)} 个 Zotero 集合: {[c['data']['name'] for c in collections]}")

    # 逐集合获取 DOI
    doi_to_collections: dict[str, list[str]] = {}
    for col in collections:
        col_name = col["data"]["name"]
        col_key = col["key"]
        items = client.get_collection_items(col_key)
        dois = client.extract_dois(items)
        logger.info(f"  集合 '{col_name}': {len(items)} 条目, {len(dois)} 个 DOI")

        for doi in dois:
            if doi not in doi_to_collections:
                doi_to_collections[doi] = []
            if col_name not in doi_to_collections[doi]:
                doi_to_collections[doi].append(col_name)

    # 合并到现有种子
    existing = load_seeds(seeds_path)
    old_count = len(existing)
    sync_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    merged = merge_dois(existing, doi_to_collections, sync_date)
    save_seeds(merged, seeds_path)

    new_count = len(merged) - old_count
    logger.info(f"种子同步完成: {old_count} → {len(merged)} (新增 {new_count})")
    return new_count
```

**Step 4: 运行测试确认通过**

Run: `pytest tests/test_sync_seeds.py -v`
Expected: 全部 PASS

**Step 5: Commit**

```bash
git add scripts/sync_seeds.py tests/test_sync_seeds.py
git commit -m "feat: add seed sync module with Zotero integration and legacy format support"
```

---

### Task 3: 主入口集成种子同步

**Files:**
- Modify: `scripts/main.py`

**Step 1: 在 main.py 中添加 `--sync-seeds` 参数和函数**

在 `run_summary()` 函数之后、`run_clear()` 之前添加：

```python
def run_sync_seeds():
    """从 Zotero 同步种子 DOI"""
    logger.info("=== 开始 Zotero 种子同步 ===")
    start = time.time()
    from scripts.sync_seeds import sync_from_zotero
    new_count = sync_from_zotero()
    logger.info(f"Zotero 种子同步完成，新增 {new_count} 个，耗时 {time.time()-start:.1f}s")
```

在 argparse 部分添加：

```python
parser.add_argument("--sync-seeds", action="store_true", help="从 Zotero 同步种子 DOI")
```

在 `run_all` 判断的 `any([...])` 列表中加入 `args.sync_seeds`。

在 try 块中、`run_fetch` 之前添加：

```python
if run_all or args.sync_seeds:
    run_sync_seeds()
```

**Step 2: 运行现有测试确认无回归**

Run: `pytest tests/test_all.py -v`
Expected: 全部 PASS（新增参数不影响默认行为）

**Step 3: Commit**

```bash
git add scripts/main.py
git commit -m "feat: integrate Zotero seed sync into main pipeline (--sync-seeds)"
```

---

### Task 4: 数据模型 — candidates.json 和 questions.json 的初始空结构

**Files:**
- Create: `data/candidates.json`
- Create: `data/questions.json`
- Create: `data/claims.json`
- Create: `data/frontier.json`
- Create: `scripts/data_models.py`

**Step 1: 写数据模型辅助函数的测试**

创建 `tests/test_data_models.py`：

```python
"""数据模型辅助函数测试"""

import json
import tempfile
from pathlib import Path

import pytest
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestDataModels:
    def test_empty_candidates(self):
        from scripts.data_models import empty_candidates
        data = empty_candidates()
        assert data == {"candidates": [], "last_updated": ""}

    def test_empty_questions(self):
        from scripts.data_models import empty_questions
        data = empty_questions()
        assert data == {"questions": [], "last_updated": ""}

    def test_empty_claims(self):
        from scripts.data_models import empty_claims
        data = empty_claims()
        assert data == {"claims": [], "last_updated": ""}

    def test_empty_frontier(self):
        from scripts.data_models import empty_frontier
        data = empty_frontier()
        assert data == {"week": "", "generated_at": "", "changes": [], "top_papers": [], "model_diff_summary": ""}

    def test_load_or_create_existing(self):
        """已有文件应直接加载"""
        from scripts.data_models import load_or_create
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            json.dump({"questions": [{"id": "q1"}]}, f)
            tmp_path = f.name
        try:
            result = load_or_create(Path(tmp_path), "questions")
            assert len(result["questions"]) == 1
        finally:
            Path(tmp_path).unlink()

    def test_load_or_create_missing(self):
        """不存在的文件应创建空结构"""
        from scripts.data_models import load_or_create
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.json"
            result = load_or_create(path, "questions")
            assert result == {"questions": [], "last_updated": ""}
            # 文件应被创建
            assert path.exists()

    def test_paper_schema_new_fields(self):
        """新论文 schema 应包含 role, question_ids, claim_ids, discovery_reason, scores"""
        from scripts.data_models import new_paper_entry
        paper = new_paper_entry(
            id="W123",
            doi="10.1234/test",
            title="Test",
            year=2025,
            abstract="abstract",
            role="promoted",
        )
        assert paper["role"] == "promoted"
        assert paper["question_ids"] == []
        assert paper["claim_ids"] == []
        assert paper["discovery_reason"] == ""
        assert paper["scores"] == {"total": 0, "components": {}}
        assert paper["analysis"] is None
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_data_models.py -v`
Expected: FAIL

**Step 3: 实现 data_models.py**

创建 `scripts/data_models.py`：

```python
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
```

**Step 4: 运行测试确认通过**

Run: `pytest tests/test_data_models.py -v`
Expected: 全部 PASS

**Step 5: Commit**

```bash
git add scripts/data_models.py tests/test_data_models.py data/candidates.json data/questions.json data/claims.json data/frontier.json
git commit -m "feat: add data model helpers and empty JSON structures for new schema"
```

---

## Phase 1: 廉价筛选漏斗

### Task 5: 廉价评分模块

**Files:**
- Create: `scripts/scoring.py`
- Create: `tests/test_scoring.py`

**Step 1: 写评分函数的失败测试**

创建 `tests/test_scoring.py`：

```python
"""廉价评分模块测试"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def make_paper(**kwargs):
    """创建测试论文"""
    defaults = {
        "id": "W1",
        "doi": "",
        "title": "Fan broadband noise prediction using LES",
        "abstract": "This paper studies broadband noise from axial fan using large eddy simulation",
        "year": 2024,
        "authors": [],
        "topics": ["Aeroacoustics"],
        "source": {"name": "AIAA Journal", "type": "journal"},
    }
    defaults.update(kwargs)
    return defaults


def make_question(**kwargs):
    """创建测试问题"""
    defaults = {
        "id": "q1",
        "name": "宽频噪声预测",
        "description": "风扇宽频噪声的产生机制与预测方法",
        "seed_dois": ["10.1234/a", "10.5678/b"],
        "keywords": ["broadband noise", "fan", "LES"],
        "methods_of_interest": ["LES", "DES"],
    }
    defaults.update(kwargs)
    return defaults


class TestScoring:
    def test_keyword_overlap_basic(self):
        from scripts.scoring import keyword_overlap_score
        score = keyword_overlap_score(
            "Fan broadband noise prediction using LES",
            ["broadband noise", "fan", "LES"],
        )
        assert score > 0
        assert score <= 3

    def test_keyword_overlap_no_match(self):
        from scripts.scoring import keyword_overlap_score
        score = keyword_overlap_score(
            "Turbine blade cooling study",
            ["broadband noise", "fan", "LES"],
        )
        assert score == 0

    def test_topic_match(self):
        from scripts.scoring import topic_match_score
        score = topic_match_score(["Aeroacoustics", "Fan Noise"], make_question())
        assert score > 0
        assert score <= 2

    def test_topic_match_no_overlap(self):
        from scripts.scoring import topic_match_score
        score = topic_match_score(["Thermodynamics"], make_question())
        assert score == 0

    def test_seed_connections(self):
        from scripts.scoring import seed_connection_score
        score = seed_connection_score(
            seed_connections=["10.1234/a", "10.5678/b"],
            question_seed_dois=["10.1234/a", "10.5678/b", "10.9999/c"],
        )
        assert score > 0  # 2 connections
        assert score <= 5  # 3 connections max + 2 bonus

    def test_seed_connections_multi_bonus(self):
        """引用 ≥3 个种子应获得额外加分"""
        from scripts.scoring import seed_connection_score
        score_few = seed_connection_score(
            seed_connections=["10.1234/a"],
            question_seed_dois=["10.1234/a", "10.5678/b", "10.9999/c"],
        )
        score_many = seed_connection_score(
            seed_connections=["10.1234/a", "10.5678/b", "10.9999/c"],
            question_seed_dois=["10.1234/a", "10.5678/b", "10.9999/c"],
        )
        assert score_many > score_few

    def test_recency_bonus(self):
        from scripts.scoring import recency_score
        assert recency_score(2026) > recency_score(2023)
        assert recency_score(2023) > recency_score(2015)

    def test_venue_match(self):
        from scripts.scoring import venue_match_score
        question = make_question()
        score = venue_match_score("AIAA Journal", question)
        # venue_match 目前基于 question 配置中是否有 venues 字段
        assert isinstance(score, (int, float))

    def test_negative_keywords_penalty(self):
        from scripts.scoring import negative_keyword_penalty
        penalty = negative_keyword_penalty(
            "Sparse matrix decomposition for combustion",
            ["sparse matrix", "combustion"],
        )
        assert penalty < 0

    def test_negative_keywords_no_penalty(self):
        from scripts.scoring import negative_keyword_penalty
        penalty = negative_keyword_penalty(
            "Fan broadband noise LES study",
            ["sparse matrix", "combustion"],
        )
        assert penalty == 0

    def test_score_candidate_integration(self):
        """完整评分流程"""
        from scripts.scoring import score_candidate
        paper = make_paper()
        question = make_question()
        result = score_candidate(
            paper=paper,
            question=question,
            seed_connections=["10.1234/a"],
        )
        assert "total" in result
        assert "components" in result
        assert result["total"] > 0
        assert result["total"] <= 14  # max theoretical score
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_scoring.py -v`
Expected: FAIL

**Step 3: 实现 scoring.py**

创建 `scripts/scoring.py`：

```python
"""廉价评分模块 — 纯 Python 计算候选论文与研究问题的匹配度"""

import re
from typing import Optional


def keyword_overlap_score(text: str, keywords: list[str]) -> float:
    """标题/摘要关键词匹配 (0-3分)

    每匹配一个关键词 +1，上限 3。
    """
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text_lower)
    return min(hits, 3.0)


def topic_match_score(paper_topics: list[str], question: dict) -> float:
    """OpenAlex topic 匹配 (0-2分)

    paper_topics: 论文的 OpenAlex topic 名称列表
    question: 包含 keywords 和 methods_of_interest
    """
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
    """种子连接数评分 (0-3分基础 + 2分多连接奖励)

    seed_connections: 候选论文连接的种子 DOI 列表
    question_seed_dois: 该问题的种子 DOI 列表
    """
    if not seed_connections or not question_seed_dois:
        return 0.0

    question_set = set(question_seed_dois)
    overlap = sum(1 for doi in seed_connections if doi in question_set)

    base = min(overlap, 3.0)
    bonus = 2.0 if overlap >= 3 else 0.0

    return base + bonus


def recency_score(year: Optional[int]) -> float:
    """年份加权 (0-1分)

    当年 +1，每过一年 -0.15，最低 0。
    """
    if not year:
        return 0.0

    current_year = 2026  # 可从 datetime 获取，但硬编码足够
    age = max(0, current_year - year)
    return max(0.0, 1.0 - age * 0.15)


def venue_match_score(venue_name: str, question: dict) -> float:
    """期刊/会议匹配 (0-1分)

    如果问题配置了 venues 列表，则检查匹配。
    """
    venues = question.get("venues", [])
    if not venues or not venue_name:
        return 0.0

    venue_lower = venue_name.lower()
    for v in venues:
        if v.lower() in venue_lower or venue_lower in v.lower():
            return 1.0
    return 0.0


def negative_keyword_penalty(text: str, negative_keywords: list[str]) -> float:
    """负面关键词惩罚 (-2分)

    匹配负面关键词时返回 -2，否则 0。
    """
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
    """计算候选论文对某个问题的综合匹配分。

    Returns:
        {"total": float, "components": {name: score, ...}}
    """
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
```

**Step 4: 运行测试确认通过**

Run: `pytest tests/test_scoring.py -v`
Expected: 全部 PASS

**Step 5: Commit**

```bash
git add scripts/scoring.py tests/test_scoring.py
git commit -m "feat: add cheap scoring module for candidate-paper relevance"
```

---

### Task 6: 候选发现重写

**Files:**
- Modify: `scripts/fetch_papers.py`

**Step 1: 重构 fetch_papers.py**

将现有 `fetch_citation_graph()` 重构为 `fetch_candidates()`，输出到 `candidates.json` 而非 `papers.json`。

修改 `scripts/fetch_papers.py`：

```python
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
    """加载 candidates.json"""
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
    """加载种子 DOI 列表（兼容新旧格式）"""
    if not SEED_DOIS_FILE.exists():
        logger.warning(f"种子 DOI 文件不存在: {SEED_DOIS_FILE}")
        return []
    with open(SEED_DOIS_FILE, "r", encoding="utf-8") as f:
        seeds = json.load(f)
    # 适配旧格式
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
) -> tuple[str, int]:
    """获取单个种子的最新引用者（路径 A）"""
    doi = seed_entry.get("doi", "")
    label = seed_entry.get("label", doi)
    client = OpenAlexClient()
    local_new = 0

    logger.info(f"获取种子引用者: {label}")

    # 获取种子论文
    raw_seed = client.get_work_by_doi(doi)
    if not raw_seed:
        logger.error(f"无法获取种子论文: {doi}")
        return doi, 0

    seed_paper = OpenAlexClient.extract_paper(raw_seed, discovery_origin="seed", seed_doi=doi)
    seed_id = seed_paper["id"]
    clean_doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

    # 将种子本身也加入候选（如果是新的）
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

    # 获取引用者（路径 A）
    if seed_id:
        one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        citing_results = client.get_citing_works(
            seed_id,
            max_results=CITATION_CONFIG.get("max_citers_per_seed", 50),
        )
        citing_count = 0
        with index_lock:
            for raw in citing_results:
                paper = OpenAlexClient.extract_paper(raw, discovery_origin="citing", seed_doi=clean_doi)
                pid = paper["id"]
                # 只保留最近 1 年的
                paper_year = paper.get("year")
                if paper_year and paper_year < datetime.now().year - 1:
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
                    # 已有候选，补充种子连接
                    if clean_doi not in candidate_index[pid]["seed_connections"]:
                        candidate_index[pid]["seed_connections"].append(clean_doi)
        logger.info(f"  引用者: 获取 {len(citing_results)} 篇, 新增 {citing_count} 篇")

    return doi, local_new


def fetch_candidates():
    """从种子 DOI 发现候选论文，写入 candidates.json"""
    # 加载现有候选（避免重复计算）
    existing_candidates = load_candidates()
    candidate_index = {}
    for c in existing_candidates.get("candidates", []):
        candidate_index[c["id"]] = c

    # 已 promoted 的论文 ID 集合
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
                logger.info(f"完成种子 {doi}: 新增 {new} 个候选")
            except Exception as e:
                logger.error(f"种子 {doi} 处理异常: {e}")

    # 保存候选
    candidates_list = sorted(
        candidate_index.values(),
        key=lambda c: (c.get("year") or 0),
        reverse=True,
    )

    save_candidates({"candidates": candidates_list})
    logger.info(f"候选发现完成，新增 {total_new} 个，总计 {len(candidates_list)} 个")


# 保留旧接口兼容
def fetch_citation_graph():
    """兼容旧接口，内部调用 fetch_candidates"""
    fetch_candidates()
```

**Step 2: 运行现有测试**

Run: `pytest tests/test_all.py::TestFetchPapers -v`
Expected: PASS（load/save 接口未变）

**Step 3: Commit**

```bash
git add scripts/fetch_papers.py
git commit -m "refactor: rewrite fetch to output candidates.json instead of papers.json"
```

---

### Task 7: 候选提升模块

**Files:**
- Create: `scripts/promote.py`
- Create: `tests/test_promote.py`

**Step 1: 写失败测试**

创建 `tests/test_promote.py`：

```python
"""候选提升模块测试"""

import json
import tempfile
from pathlib import Path

import pytest
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def make_candidate(**kwargs):
    defaults = {
        "id": "W1",
        "doi": "10.1234/test",
        "title": "Fan broadband noise study",
        "abstract": "LES of broadband noise in axial fan",
        "year": 2024,
        "topics": ["Aeroacoustics"],
        "source": {"name": "AIAA Journal"},
        "discovered_via": "citing_seed",
        "seed_connections": ["10.seed/a"],
        "promoted": False,
    }
    defaults.update(kwargs)
    return defaults


def make_question(**kwargs):
    defaults = {
        "id": "q1",
        "name": "宽频噪声",
        "seed_dois": ["10.seed/a"],
        "keywords": ["broadband noise", "fan", "LES"],
        "methods_of_interest": ["LES"],
    }
    defaults.update(kwargs)
    return defaults


class TestPromote:
    def test_score_and_rank(self):
        from scripts.promote import score_and_rank_candidates
        candidates = [
            make_candidate(id="W1", title="Fan broadband noise LES"),
            make_candidate(id="W2", title="Unrelated thermodynamics paper"),
            make_candidate(id="W3", title="Broadband noise from axial fan rotor"),
        ]
        questions = [make_question()]

        scored = score_and_rank_candidates(candidates, questions)
        assert len(scored) == 3
        # W1 和 W3 应该得分高于 W2
        assert scored[0]["scores"]["total"] >= scored[-1]["scores"]["total"]

    def test_promote_top_n(self):
        from scripts.promote import promote_top_n
        scored = [
            {"id": "W1", "scores": {"total": 8.0}, "best_question": "q1", "promoted": False},
            {"id": "W2", "scores": {"total": 6.0}, "best_question": "q1", "promoted": False},
            {"id": "W3", "scores": {"total": 4.0}, "best_question": "q1", "promoted": False},
            {"id": "W4", "scores": {"total": 3.0}, "best_question": "q1", "promoted": False},
        ]

        promoted = promote_top_n(scored, threshold=5.0, per_question_limit=5, global_limit=30)
        assert len(promoted) == 2  # W1 and W2 above threshold
        assert promoted[0]["id"] == "W1"
        assert promoted[1]["id"] == "W2"

    def test_promote_respects_per_question_limit(self):
        from scripts.promote import promote_top_n
        scored = [
            {"id": f"W{i}", "scores": {"total": 8.0}, "best_question": "q1", "promoted": False}
            for i in range(10)
        ]

        promoted = promote_top_n(scored, threshold=5.0, per_question_limit=3, global_limit=30)
        assert len(promoted) == 3

    def test_promote_skips_already_promoted(self):
        from scripts.promote import promote_top_n
        scored = [
            {"id": "W1", "scores": {"total": 8.0}, "best_question": "q1", "promoted": True},
            {"id": "W2", "scores": {"total": 7.0}, "best_question": "q1", "promoted": False},
        ]

        promoted = promote_top_n(scored, threshold=5.0, per_question_limit=5, global_limit=30)
        assert len(promoted) == 1
        assert promoted[0]["id"] == "W2"
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_promote.py -v`
Expected: FAIL

**Step 3: 实现 promote.py**

创建 `scripts/promote.py`：

```python
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
    """对所有候选论文评分并排序。

    每个候选对每个问题计算分数，保留最高分和对应问题。

    Returns:
        按最高分降序排列的候选列表，每项增加 scores 和 best_question 字段
    """
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
    """从已评分候选中提升 top N 为 promoted 论文。

    规则：
    1. 分数 ≥ threshold
    2. 每个问题最多提升 per_question_limit 篇
    3. 全局最多提升 global_limit 篇
    4. 已 promoted 的跳过

    Returns:
        本次被提升的候选列表
    """
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
    """执行候选提升流程。

    Returns:
        本次提升的论文数量
    """
    # 加载候选
    if not CANDIDATES_FILE.exists():
        logger.warning("candidates.json 不存在，跳过提升")
        return 0

    with open(CANDIDATES_FILE, "r", encoding="utf-8") as f:
        candidates_data = json.load(f)
    candidates = candidates_data.get("candidates", [])

    # 加载问题
    questions_file = DATA_DIR / "questions.json"
    if questions_file.exists():
        with open(questions_file, "r", encoding="utf-8") as f:
            questions_data = json.load(f)
        questions = questions_data.get("questions", [])
    else:
        # 没有问题图谱时，使用空关键词列表做通用评分
        questions = [{"id": "_default", "keywords": [], "seed_dois": [], "methods_of_interest": []}]

    # 评分排序
    scored = score_and_rank_candidates(candidates, questions)

    # 提升
    promoted = promote_top_n(scored)

    if not promoted:
        logger.info("没有候选达到提升阈值")
        # 回写候选评分
        candidates_data["candidates"] = scored
        save_json(candidates_data, CANDIDATES_FILE)
        return 0

    # 将提升的候选写入 papers.json
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

    # 回写候选（包含评分结果和 promoted 状态）
    candidates_data["candidates"] = scored
    save_json(candidates_data, CANDIDATES_FILE)

    logger.info(f"提升完成: {added} 篇候选提升为论文, 总计 {len(papers_data['papers'])} 篇")
    return added
```

**Step 4: 运行测试确认通过**

Run: `pytest tests/test_promote.py -v`
Expected: 全部 PASS

**Step 5: Commit**

```bash
git add scripts/promote.py tests/test_promote.py
git commit -m "feat: add candidate promotion module with scoring, ranking, and threshold-based selection"
```

---

### Task 8: 流水线集成

**Files:**
- Modify: `scripts/main.py`

**Step 1: 更新 main.py 流水线**

添加 `run_promote()` 函数和 `--promote-only` 参数。修改完整流水线顺序为：sync-seeds → fetch → promote → analyze → groups → trends → summary。

在 `run_fetch()` 之后添加：

```python
def run_promote():
    """运行候选提升"""
    logger.info("=== 开始候选提升 ===")
    start = time.time()
    from scripts.promote import run_promotion
    count = run_promotion()
    logger.info(f"候选提升完成，提升 {count} 篇，耗时 {time.time()-start:.1f}s")
```

在 argparse 中添加：

```python
parser.add_argument("--promote-only", action="store_true", help="仅提升候选论文")
```

更新 `run_all` 的判断和执行顺序：

```python
run_all = args.all or not any([
    args.sync_seeds, args.fetch_only, args.promote_only, args.analyze_only,
    args.trends_only, args.groups_only, args.summary_only,
])

# ...

if run_all or args.sync_seeds:
    run_sync_seeds()
if run_all or args.fetch_only:
    run_fetch()
if run_all or args.promote_only:
    run_promote()
if run_all or args.analyze_only:
    run_analyze()
if run_all or args.groups_only:
    run_groups()
if run_all or args.trends_only:
    run_trends()
if run_all or args.summary_only:
    run_summary()
```

**Step 2: 运行全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS

**Step 3: Commit**

```bash
git add scripts/main.py
git commit -m "feat: integrate promotion step into pipeline (sync → fetch → promote → analyze)"
```

---

## Phase 2: 问题图谱 + 主张提取

### Task 9: 问题图谱初始化

**Files:**
- Create: `scripts/init_questions.py`
- Create: `tests/test_init_questions.py`
- Modify: `scripts/deepseek_client.py`
- Modify: `scripts/main.py`

**Step 1: 写测试**

创建 `tests/test_init_questions.py`：

```python
"""问题图谱初始化测试"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestInitQuestions:
    def test_build_seed_info_text(self):
        """应将种子论文信息格式化为文本"""
        from scripts.init_questions import build_seed_info_text
        seeds = [
            {"doi": "10.1234/a", "zotero_collections": ["宽频噪声"]},
            {"doi": "10.5678/b", "zotero_collections": ["声衬设计"]},
        ]
        # 模拟 papers 数据
        papers_by_doi = {
            "10.1234/a": {"title": "Fan broadband noise", "abstract": "LES study..."},
            "10.5678/b": {"title": "Liner design", "abstract": "Acoustic liner..."},
        }
        text = build_seed_info_text(seeds, papers_by_doi)
        assert "宽频噪声" in text
        assert "Fan broadband noise" in text
        assert "声衬设计" in text

    def test_build_seed_info_grouped_by_collection(self):
        """应按集合分组展示"""
        from scripts.init_questions import build_seed_info_text
        seeds = [
            {"doi": "10.1/a", "zotero_collections": ["col1"]},
            {"doi": "10.2/b", "zotero_collections": ["col1"]},
            {"doi": "10.3/c", "zotero_collections": ["col2"]},
        ]
        papers_by_doi = {
            "10.1/a": {"title": "A", "abstract": ""},
            "10.2/b": {"title": "B", "abstract": ""},
            "10.3/c": {"title": "C", "abstract": ""},
        }
        text = build_seed_info_text(seeds, papers_by_doi)
        # col1 应在 col2 之前出现
        idx1 = text.index("col1")
        idx2 = text.index("col2")
        assert idx1 < idx2

    def test_parse_questions_response_valid(self):
        """应正确解析 DeepSeek 返回的问题 JSON"""
        from scripts.init_questions import parse_questions_response
        response = json.dumps({
            "questions": [
                {
                    "name": "宽频噪声预测",
                    "description": "风扇宽频噪声的产生机制",
                    "keywords": ["broadband noise", "fan"],
                    "seed_dois": ["10.1234/a"],
                }
            ]
        })
        questions = parse_questions_response(response)
        assert len(questions) == 1
        assert questions[0]["id"].startswith("q_")
        assert questions[0]["status"] == "active"

    def test_parse_questions_response_generates_ids(self):
        """每个问题应有唯一 ID"""
        from scripts.init_questions import parse_questions_response
        response = json.dumps({
            "questions": [
                {"name": "Q1", "description": "D1", "keywords": ["k1"], "seed_dois": []},
                {"name": "Q2", "description": "D2", "keywords": ["k2"], "seed_dois": []},
            ]
        })
        questions = parse_questions_response(response)
        ids = {q["id"] for q in questions}
        assert len(ids) == 2
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_init_questions.py -v`
Expected: FAIL

**Step 3: 添加 DeepSeek 方法**

在 `scripts/deepseek_client.py` 中添加 `cluster_questions` 方法：

```python
def cluster_questions(self, seed_info_text: str) -> str:
    """将种子论文信息聚类为研究问题"""
    system_prompt = """你是一位风扇噪声领域的学术专家。请将以下种子论文按研究主题聚类为 6-12 个研究问题。

每个问题应包含：
- name: 简短的问题名称（中文）
- description: 问题描述（中文，1-2句话）
- keywords: 英文关键词列表（用于匹配论文标题/摘要）
- methods_of_interest: 感兴趣的研究方法列表
- seed_dois: 属于该问题的种子论文 DOI 列表

请返回JSON格式：
{"questions": [{"name": "...", "description": "...", "keywords": [...], "methods_of_interest": [...], "seed_dois": [...]}]}

要求：
1. 问题数量在 6-12 之间
2. 每个种子论文至少归入一个问题
3. 如果一个种子论文涉及多个问题，可以重复出现
4. 关键词应具体且有区分度
5. 参考用户在 Zotero 中的分组（如有），但不必完全一致"""

    return self._call(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": seed_info_text},
        ],
        max_tokens=4000,
        temperature=0.3,
        json_mode=True,
    )
```

**Step 4: 实现 init_questions.py**

创建 `scripts/init_questions.py`：

```python
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
    # 按集合分组
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

    # 格式化
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
        # 尝试从 markdown 代码块中提取
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
        # 生成 ID：从中文名称的拼音或英文关键词
        base_id = re.sub(r"[^a-zA-Z0-9一-鿿]", "_", name).strip("_").lower()
        if not base_id:
            base_id = f"q_{len(result) + 1}"
        qid = f"q_{base_id}"
        # 确保唯一
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
    """初始化问题图谱

    Args:
        force: 是否强制重新聚类（覆盖现有 questions.json）
    """
    # 检查是否已有问题
    if QUESTIONS_FILE.exists() and not force:
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("questions"):
            logger.info(f"问题图谱已存在（{len(data['questions'])} 个问题），跳过初始化。使用 --init-questions 强制重建。")
            return

    # 加载种子
    if not SEED_DOIS_FILE.exists():
        logger.error("seed_dois.json 不存在，无法初始化问题图谱")
        return

    with open(SEED_DOIS_FILE, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    if not seeds:
        logger.warning("种子列表为空")
        return

    # 加载种子论文的标题/摘要（从 papers.json 或 OpenAlex）
    papers_by_doi = {}
    if PAPERS_FILE.exists():
        with open(PAPERS_FILE, "r", encoding="utf-8") as f:
            papers_data = json.load(f)
        for p in papers_data.get("papers", []):
            doi = (p.get("doi") or "").replace("https://doi.org/", "").lower()
            if doi:
                papers_by_doi[doi] = {"title": p.get("title", ""), "abstract": p.get("abstract", "")}

    # 对于没有标题/摘要的种子，从 OpenAlex 获取
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

    # 构建种子信息文本
    seed_text = build_seed_info_text(seeds, papers_by_doi)

    # 调用 DeepSeek 聚类
    logger.info(f"调用 DeepSeek 聚类 {len(seeds)} 篇种子论文...")
    ds_client = DeepSeekClient()
    response = ds_client.cluster_questions(seed_text)
    questions = parse_questions_response(response)

    # 保存
    data = empty_questions()
    data["questions"] = questions
    save_json(data, QUESTIONS_FILE)

    logger.info(f"问题图谱初始化完成: {len(questions)} 个问题")
    for q in questions:
        logger.info(f"  - {q['id']}: {q['name']} ({len(q['seed_dois'])} 篇种子)")
```

**Step 5: 添加 main.py 集成**

在 `main.py` 中添加 `--init-questions` 参数和函数：

```python
def run_init_questions():
    """初始化问题图谱"""
    logger.info("=== 开始问题图谱初始化 ===")
    start = time.time()
    from scripts.init_questions import init_questions
    init_questions(force=True)
    logger.info(f"问题图谱初始化完成，耗时 {time.time()-start:.1f}s")
```

在 argparse 中添加：

```python
parser.add_argument("--init-questions", action="store_true", help="强制重新初始化问题图谱")
```

在 try 块中，sync-seeds 之后添加：

```python
if args.init_questions:
    run_init_questions()
```

**Step 6: 运行测试确认通过**

Run: `pytest tests/test_init_questions.py tests/test_all.py -v`
Expected: 全部 PASS

**Step 7: Commit**

```bash
git add scripts/init_questions.py scripts/deepseek_client.py scripts/main.py tests/test_init_questions.py
git commit -m "feat: add question graph initialization via DeepSeek clustering"
```

---

### Task 10: 结构化主张提取

**Files:**
- Create: `scripts/extract_claims.py`
- Create: `tests/test_extract_claims.py`
- Modify: `scripts/deepseek_client.py`

**Step 1: 写测试**

创建 `tests/test_extract_claims.py`：

```python
"""结构化主张提取测试"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestExtractClaims:
    def test_parse_claims_response(self):
        from scripts.extract_claims import parse_claims_response
        response = json.dumps({
            "claims": [
                {
                    "statement": "锯齿尾缘降低宽频噪声 3-5dB",
                    "method": "LES + FW-H",
                    "evidence_type": "numerical",
                    "geometry": "axial fan",
                    "condition": "uniform inflow",
                    "outcome": "3-5dB reduction",
                    "limitation": "未实验验证",
                }
            ],
            "relevance_to_question": 8,
            "novelty": "incremental",
            "question_affinity": ["q_broadband"],
        })
        result = parse_claims_response(response, paper_id="W123", question_id="q_broadband")
        assert len(result["claims"]) == 1
        assert result["claims"][0]["supporting_papers"] == ["W123"]
        assert result["claims"][0]["question_id"] == "q_broadband"
        assert result["claims"][0]["id"].startswith("claim_")

    def test_parse_claims_response_empty(self):
        from scripts.extract_claims import parse_claims_response
        response = json.dumps({"claims": [], "relevance_to_question": 0, "novelty": "review", "question_affinity": []})
        result = parse_claims_response(response, paper_id="W123", question_id="q1")
        assert result["claims"] == []

    def test_parse_claims_generates_unique_ids(self):
        from scripts.extract_claims import parse_claims_response
        response = json.dumps({
            "claims": [
                {"statement": "A", "method": "M1", "evidence_type": "numerical", "geometry": "", "condition": "", "outcome": "", "limitation": ""},
                {"statement": "B", "method": "M2", "evidence_type": "experiment", "geometry": "", "condition": "", "outcome": "", "limitation": ""},
            ],
            "relevance_to_question": 7,
            "novelty": "novel",
            "question_affinity": ["q1"],
        })
        result = parse_claims_response(response, paper_id="W1", question_id="q1")
        ids = {c["id"] for c in result["claims"]}
        assert len(ids) == 2
```

**Step 2: 运行测试确认失败**

Run: `pytest tests/test_extract_claims.py -v`
Expected: FAIL

**Step 3: 添加 DeepSeek 方法**

在 `scripts/deepseek_client.py` 中添加：

```python
CLAIM_EXTRACTION_PROMPT = """你是一位风扇噪声领域的学术分析助手。请从以下论文中提取结构化信息。

请以JSON格式返回：
{
  "claims": [
    {
      "statement": "核心主张的一句话描述（中文）",
      "method": "使用的研究方法",
      "evidence_type": "experiment | numerical | analytical | review",
      "geometry": "涉及的几何构型",
      "condition": "工况条件",
      "outcome": "主要结果/发现",
      "limitation": "作者声明的局限性"
    }
  ],
  "relevance_to_question": 与指定研究问题的关联度(1-10),
  "novelty": "novel | incremental | review | replication",
  "question_affinity": ["最相关的问题ID"]
}

要求：
1. 主张应具体、可验证
2. 如果论文没有明确的主张（如纯方法论），可以留空 claims
3. evidence_type 必须是四个选项之一
4. 不要编造论文中没有的信息"""

def extract_claims(self, title: str, abstract: str, question_name: str = "") -> dict:
    """从论文中提取结构化主张"""
    if not abstract.strip():
        return {"claims": [], "relevance_to_question": 0, "novelty": "unknown", "question_affinity": []}

    user_msg = f"论文标题：{title}\n\n论文摘要：{abstract}"
    if question_name:
        user_msg += f"\n\n关联的研究问题：{question_name}"

    try:
        result_text = self._call(
            messages=[
                {"role": "system", "content": self.CLAIM_EXTRACTION_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=1500,
            temperature=0.2,
            json_mode=True,
        )
        return json.loads(result_text)
    except json.JSONDecodeError as e:
        logger.error(f"DeepSeek 返回非法 JSON: {e}")
        return {"claims": [], "relevance_to_question": 0, "novelty": "unknown", "question_affinity": [], "error": True}
    except Exception as e:
        logger.error(f"主张提取失败 '{title[:50]}': {e}")
        raise
```

**Step 4: 实现 extract_claims.py**

创建 `scripts/extract_claims.py`：

```python
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

    # 加载问题（用于提供问题名称）
    questions_map = {}
    if QUESTIONS_FILE.exists():
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            for q in json.load(f).get("questions", []):
                questions_map[q["id"]] = q

    # 加载现有主张
    if CLAIMS_FILE.exists():
        with open(CLAIMS_FILE, "r", encoding="utf-8") as f:
            claims_data = json.load(f)
    else:
        claims_data = {"claims": [], "last_updated": ""}

    existing_claim_ids = {c["id"] for c in claims_data["claims"]}

    # 筛选待处理论文
    to_extract = []
    for p in papers:
        if p.get("role") not in ("seed", "promoted"):
            continue
        if p.get("analysis") is not None and not force:
            # 已有旧分析但没有 claims — 标记为待迁移
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
    save_lock = threading.Lock()
    progress = [0]
    new_claims = []

    def _extract_one(idx, paper):
        qids = paper.get("question_ids", [])
        q_name = ""
        if qids:
            q = questions_map.get(qids[0], {})
            q_name = q.get("name", "")

        result = client.extract_claims(
            title=paper.get("title", ""),
            abstract=paper.get("abstract", ""),
            question_name=q_name,
        )

        # 更新论文的 analysis 和 claim_ids
        paper["analysis"] = {
            "claims_summary": result,
            "relevance_to_question": result.get("relevance_to_question", 0),
            "novelty": result.get("novelty", "unknown"),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        claim_ids = []
        for claim in result.get("claims", []):
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

    # 保存
    claims_data["claims"].extend(new_claims)
    claims_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(CLAIMS_FILE, "w", encoding="utf-8") as f:
        json.dump(claims_data, f, ensure_ascii=False, indent=2)

    papers_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(PAPERS_FILE, "w", encoding="utf-8") as f:
        json.dump(papers_data, f, ensure_ascii=False, indent=2)

    logger.info(f"主张提取完成: {len(new_claims)} 条新主张, 总计 {len(claims_data['claims'])} 条")
```

**Step 5: 运行测试确认通过**

Run: `pytest tests/test_extract_claims.py -v`
Expected: 全部 PASS

**Step 6: Commit**

```bash
git add scripts/extract_claims.py scripts/deepseek_client.py tests/test_extract_claims.py
git commit -m "feat: add structured claim extraction from promoted papers"
```

---

### Task 11: 问题状态更新

**Files:**
- Create: `scripts/update_questions.py`

**Step 1: 实现**

创建 `scripts/update_questions.py`：

```python
"""问题状态更新模块 — 根据新证据更新研究问题的状态"""

import json
import logging
from datetime import datetime, timezone

from scripts.config import DATA_DIR
from scripts.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

QUESTIONS_FILE = DATA_DIR / "questions.json"
CLAIMS_FILE = DATA_DIR / "claims.json"


def update_question_states():
    """对有新证据的研究问题更新状态"""
    if not QUESTIONS_FILE.exists():
        logger.warning("questions.json 不存在，跳过问题状态更新")
        return

    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        questions_data = json.load(f)
    questions = questions_data.get("questions", [])

    if not questions:
        return

    # 加载主张
    claims = []
    if CLAIMS_FILE.exists():
        with open(CLAIMS_FILE, "r", encoding="utf-8") as f:
            claims = json.load(f).get("claims", [])

    client = DeepSeekClient()
    updated_count = 0

    for question in questions:
        qid = question["id"]
        q_claims = [c for c in claims if c.get("question_id") == qid]

        if not q_claims:
            continue

        # 构建主张摘要
        claims_text = "\n".join(
            f"- [{c.get('evidence_type', '?')}] {c.get('statement', '')} "
            f"(方法: {c.get('method', '?')}, 结果: {c.get('outcome', '?')})"
            for c in q_claims[:20]  # 最多 20 条
        )

        prompt = f"""研究问题：{question['name']}
问题描述：{question['description']}

当前主张：
{claims_text}

请分析：
1. 当前证据的整体强度如何？
2. 是否存在矛盾的证据？
3. 还存在哪些明显的研究差距？
4. 是否出现新的研究趋势？

以JSON格式返回：
{{
  "evidence_strength": "strong | moderate | weak",
  "gaps": ["差距1", "差距2"],
  "emerging_trends": ["趋势1"],
  "contradictions": ["矛盾描述"],
  "status_update": "一句话状态总结"
}}"""

        try:
            result_text = client._call(
                messages=[
                    {"role": "system", "content": "你是风扇噪声研究领域的分析专家。"},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1000,
                temperature=0.3,
                json_mode=True,
            )
            result = json.loads(result_text)

            question["gap_flags"] = result.get("gaps", [])
            question["evidence_count"] = len(q_claims)
            question["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # 将状态更新信息附加到 question
            if "_status_log" not in question:
                question["_status_log"] = []
            question["_status_log"].append({
                "date": question["last_updated"],
                "update": result.get("status_update", ""),
                "evidence_strength": result.get("evidence_strength", ""),
            })

            updated_count += 1
            logger.info(f"问题 '{question['name']}' 状态已更新: {result.get('status_update', '')[:60]}...")

        except Exception as e:
            logger.error(f"问题 '{question['name']}' 更新失败: {e}")

    if updated_count:
        questions_data["questions"] = questions
        questions_data["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(QUESTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(questions_data, f, ensure_ascii=False, indent=2)

    logger.info(f"问题状态更新完成: {updated_count}/{len(questions)} 个问题已更新")
```

**Step 2: Commit**

```bash
git add scripts/update_questions.py
git commit -m "feat: add question state update based on claim evidence"
```

---

### Task 12: 前沿差异生成

**Files:**
- Create: `scripts/generate_frontier.py`
- Modify: `scripts/main.py`

**Step 1: 实现 generate_frontier.py**

创建 `scripts/generate_frontier.py`：

```python
"""前沿差异生成模块 — 生成每周的模型变化报告"""

import json
import logging
from datetime import datetime, timezone

from scripts.config import DATA_DIR
from scripts.deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

FRONTIER_FILE = DATA_DIR / "frontier.json"
QUESTIONS_FILE = DATA_DIR / "questions.json"
CLAIMS_FILE = DATA_DIR / "claims.json"
PAPERS_FILE = DATA_DIR / "papers.json"


def generate_frontier_report():
    """生成本周前沿差异报告"""
    # 加载数据
    questions = []
    if QUESTIONS_FILE.exists():
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            questions = json.load(f).get("questions", [])

    claims = []
    if CLAIMS_FILE.exists():
        with open(CLAIMS_FILE, "r", encoding="utf-8") as f:
            claims = json.load(f).get("claims", [])

    papers = []
    if PAPERS_FILE.exists():
        with open(PAPERS_FILE, "r", encoding="utf-8") as f:
            papers = json.load(f).get("papers", [])

    # 构建变化摘要
    recent_papers = [p for p in papers if p.get("role") == "promoted"]
    recent_claims = claims[-20:]  # 最近 20 条主张

    # 按问题汇总
    question_summaries = []
    for q in questions:
        qid = q["id"]
        q_claims = [c for c in claims if c.get("question_id") == qid]
        q_papers = [p for p in recent_papers if qid in p.get("question_ids", [])]
        if q_claims or q_papers:
            question_summaries.append({
                "id": qid,
                "name": q.get("name", ""),
                "evidence_count": len(q_claims),
                "recent_papers": len(q_papers),
                "gaps": q.get("gap_flags", []),
                "status": q.get("status", ""),
            })

    # 调用 DeepSeek 生成周报
    now = datetime.now(timezone.utc)
    week_str = now.strftime("%Y-W%V")

    summary_text = f"本周概览：\n"
    summary_text += f"- 研究问题: {len(questions)} 个\n"
    summary_text += f"- 主张总数: {len(claims)} 条\n"
    summary_text += f"- 论文总数: {len(papers)} 篇\n\n"

    for qs in question_summaries:
        summary_text += f"问题 '{qs['name']}': {qs['evidence_count']} 条主张, {qs['recent_papers']} 篇论文"
        if qs["gaps"]:
            summary_text += f", 差距: {', '.join(qs['gaps'])}"
        summary_text += "\n"

    # 最近主张
    if recent_claims:
        summary_text += "\n最近主张：\n"
        for c in recent_claims[:10]:
            summary_text += f"- [{c.get('evidence_type', '?')}] {c.get('statement', '')}\n"

    try:
        client = DeepSeekClient()
        report_text = client._call(
            messages=[
                {
                    "role": "system",
                    "content": "你是风扇噪声研究领域的分析助手。请根据以下数据生成一份简洁的中文周报。"
                               "包括：最重要的发现、新兴趋势、持续差距、推荐阅读方向。"
                               "以JSON格式返回：{\"summary\": \"...\", \"key_findings\": [...], \"trends\": [...], \"gaps\": [...], \"recommended_reads\": [...]}"
                },
                {"role": "user", "content": summary_text},
            ],
            max_tokens=2000,
            temperature=0.3,
            json_mode=True,
        )
        report = json.loads(report_text)
    except Exception as e:
        logger.error(f"前沿周报生成失败: {e}")
        report = {"summary": summary_text, "key_findings": [], "trends": [], "gaps": [], "recommended_reads": []}

    # 构建 frontier.json
    frontier = {
        "week": week_str,
        "generated_at": now.isoformat(),
        "changes": [],
        "top_papers": [],
        "model_diff_summary": report.get("summary", ""),
        "key_findings": report.get("key_findings", []),
        "trends": report.get("trends", []),
        "gaps": report.get("gaps", []),
        "recommended_reads": report.get("recommended_reads", []),
        "question_summaries": question_summaries,
    }

    # 添加变化条目
    for qs in question_summaries:
        if qs["recent_papers"] > 0:
            frontier["changes"].append({
                "type": "new_evidence",
                "question_id": qs["id"],
                "summary": f"{qs['name']}方向新增{qs['recent_papers']}篇论文",
            })
    for qs in question_summaries:
        if qs["gaps"]:
            frontier["changes"].append({
                "type": "gap_persisting",
                "question_id": qs["id"],
                "description": "; ".join(qs["gaps"]),
            })

    with open(FRONTIER_FILE, "w", encoding="utf-8") as f:
        json.dump(frontier, f, ensure_ascii=False, indent=2)

    logger.info(f"前沿周报生成完成: {week_str}, {len(frontier['changes'])} 项变化")
```

**Step 2: main.py 集成**

添加 `run_frontier()` 函数和执行顺序：

```python
def run_frontier():
    """生成前沿差异报告"""
    logger.info("=== 开始前沿差异生成 ===")
    start = time.time()
    from scripts.generate_frontier import generate_frontier_report
    generate_frontier_report()
    logger.info(f"前沿差异生成完成，耗时 {time.time()-start:.1f}s")
```

更新执行顺序（在 analyze 之后、groups 之前）：

```python
if run_all or args.analyze_only:
    run_analyze()
# 新增：主张提取、问题更新、前沿生成
from scripts.extract_claims import extract_claims_for_papers
from scripts.update_questions import update_question_states
if run_all:
    extract_claims_for_papers()
    update_question_states()
    run_frontier()
if run_all or args.groups_only:
    run_groups()
```

**Step 3: 运行全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS

**Step 4: Commit**

```bash
git add scripts/generate_frontier.py scripts/main.py
git commit -m "feat: add frontier report generation and integrate claim/question updates into pipeline"
```

---

## Phase 3: 前端重构

### Task 13: 前端数据加载扩展

**Files:**
- Modify: `index.html`

**Step 1: 在 index.html 的数据加载部分添加新文件加载**

找到现有 `fetch('data/papers.json')` 等加载逻辑附近，添加：

```javascript
// 新数据文件加载
let questionsData = { questions: [] };
let claimsData = { claims: [] };
let frontierData = { week: '', changes: [], key_findings: [], trends: [], gaps: [], recommended_reads: [], question_summaries: [] };
let candidatesData = { candidates: [] };

async function loadNewData() {
    try {
        const [qRes, cRes, fRes] = await Promise.all([
            fetch('data/questions.json').then(r => r.json()).catch(() => ({ questions: [] })),
            fetch('data/claims.json').then(r => r.json()).catch(() => ({ claims: [] })),
            fetch('data/frontier.json').then(r => r.json()).catch(() => ({ week: '', changes: [], key_findings: [], trends: [], gaps: [], recommended_reads: [], question_summaries: [] })),
        ]);
        questionsData = qRes;
        claimsData = cRes;
        frontierData = fRes;
    } catch (e) {
        console.warn('新数据文件加载失败:', e);
    }
}
```

在现有的页面初始化流程中调用 `await loadNewData()`。

**Step 2: Commit**

```bash
git add index.html
git commit -m "feat: add frontend data loading for questions, claims, and frontier"
```

---

### Task 14: 研究问题仪表盘（新首页）

**Files:**
- Modify: `index.html`

**Step 1: 添加新 tab HTML**

在现有 tab 导航中，在 dashboard 之前添加 "questions" tab：

```html
<button class="tab-btn active" data-tab="questions">研究问题</button>
```

添加对应的 tab 内容面板：

```html
<div class="tab-panel active" id="tab-questions">
    <div class="questions-header">
        <h2>研究问题仪表盘</h2>
        <p class="questions-meta">
            上次更新: <span id="questions-last-updated">-</span> |
            种子: <span id="questions-seed-count">-</span> |
            问题: <span id="questions-count">-</span>
        </p>
    </div>
    <div class="questions-grid" id="questionsGrid">
        <!-- 问题卡片由 JS 渲染 -->
    </div>
</div>
```

**Step 2: 添加渲染函数**

```javascript
function renderQuestionsDashboard() {
    const grid = document.getElementById('questionsGrid');
    if (!grid || !questionsData.questions.length) {
        if (grid) grid.innerHTML = '<p class="empty-state">问题图谱尚未初始化。运行 <code>python -m scripts.main --init-questions</code> 生成。</p>';
        return;
    }

    document.getElementById('questions-count').textContent = questionsData.questions.length;
    document.getElementById('questions-last-updated').textContent = questionsData.last_updated || '-';

    grid.innerHTML = questionsData.questions.map(q => {
        const qClaims = claimsData.claims.filter(c => c.question_id === q.id);
        const qPapers = papersData.papers.filter(p => (p.question_ids || []).includes(q.id));
        const latestClaims = qClaims.slice(-3);
        const gaps = q.gap_flags || [];
        const statusClass = q.status === 'active' ? 'status-active' : 'status-dormant';

        return `
        <div class="question-card" onclick="showQuestionDetail('${q.id}')">
            <div class="question-card-header">
                <h3>${escapeHtml(q.name)}</h3>
                <span class="status-badge ${statusClass}">${q.status}</span>
            </div>
            <p class="question-desc">${escapeHtml(q.description)}</p>
            <div class="question-stats">
                <span>证据: ${qClaims.length} 条</span>
                <span>论文: ${qPapers.length} 篇</span>
            </div>
            ${latestClaims.length ? `
            <div class="question-latest-claims">
                <strong>最新主张:</strong>
                ${latestClaims.map(c => `<p class="claim-preview">${escapeHtml(c.statement)} <span class="claim-type">(${c.evidence_type})</span></p>`).join('')}
            </div>
            ` : ''}
            ${gaps.length ? `
            <div class="question-gaps">
                <strong>研究差距:</strong> ${gaps.map(g => `<span class="gap-tag">${escapeHtml(g)}</span>`).join(' ')}
            </div>
            ` : ''}
        </div>`;
    }).join('');
}
```

**Step 3: 添加 CSS 样式**

```css
.questions-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
    padding: 16px 0;
}
.question-card {
    background: var(--card-bg, #fff);
    border: 1px solid var(--border-color, #e0e0e0);
    border-radius: 8px;
    padding: 16px;
    cursor: pointer;
    transition: box-shadow 0.2s;
}
.question-card:hover {
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.question-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}
.question-card-header h3 {
    margin: 0;
    font-size: 1.1em;
}
.status-badge {
    font-size: 0.75em;
    padding: 2px 8px;
    border-radius: 12px;
}
.status-active {
    background: #e8f5e9;
    color: #2e7d32;
}
.status-dormant {
    background: #fff3e0;
    color: #e65100;
}
.question-desc {
    font-size: 0.9em;
    color: var(--text-secondary, #666);
    margin: 8px 0;
}
.question-stats {
    display: flex;
    gap: 16px;
    font-size: 0.85em;
    color: var(--text-secondary, #666);
    margin: 8px 0;
}
.question-latest-claims {
    margin-top: 8px;
    font-size: 0.85em;
}
.claim-preview {
    margin: 4px 0;
    color: var(--text-primary, #333);
}
.claim-type {
    color: var(--text-secondary, #888);
    font-size: 0.9em;
}
.gap-tag {
    display: inline-block;
    background: #fff8e1;
    color: #f57f17;
    font-size: 0.8em;
    padding: 1px 6px;
    border-radius: 4px;
    margin: 2px;
}
```

**Step 4: Commit**

```bash
git add index.html
git commit -m "feat: add research questions dashboard as new homepage"
```

---

### Task 15: 前沿周报页

**Files:**
- Modify: `index.html`

**Step 1: 添加 tab 和渲染函数**

```html
<button class="tab-btn" data-tab="frontier">前沿周报</button>
```

```html
<div class="tab-panel" id="tab-frontier">
    <div class="frontier-header">
        <h2>前沿周报</h2>
        <p class="frontier-week">第 <span id="frontier-week">-</span> 周</p>
    </div>
    <div id="frontierContent">
        <p class="empty-state">暂无周报数据</p>
    </div>
</div>
```

```javascript
function renderFrontier() {
    const container = document.getElementById('frontierContent');
    if (!frontierData.week) {
        return;
    }

    document.getElementById('frontier-week').textContent = frontierData.week;

    let html = '';

    // 模型变化摘要
    if (frontierData.model_diff_summary) {
        html += `<div class="frontier-section"><h3>本周概览</h3><p>${escapeHtml(frontierData.model_diff_summary)}</p></div>`;
    }

    // 重要发现
    if (frontierData.key_findings && frontierData.key_findings.length) {
        html += `<div class="frontier-section"><h3>最重要的发现</h3><ul>`;
        frontierData.key_findings.forEach(f => {
            html += `<li>${escapeHtml(typeof f === 'string' ? f : f.summary || JSON.stringify(f))}</li>`;
        });
        html += `</ul></div>`;
    }

    // 新兴趋势
    if (frontierData.trends && frontierData.trends.length) {
        html += `<div class="frontier-section"><h3>新兴趋势</h3><ul>`;
        frontierData.trends.forEach(t => {
            html += `<li class="trend-item">${escapeHtml(typeof t === 'string' ? t : t.description || JSON.stringify(t))}</li>`;
        });
        html += `</ul></div>`;
    }

    // 持续差距
    if (frontierData.gaps && frontierData.gaps.length) {
        html += `<div class="frontier-section"><h3>研究差距</h3><ul>`;
        frontierData.gaps.forEach(g => {
            html += `<li class="gap-item">${escapeHtml(typeof g === 'string' ? g : g.description || JSON.stringify(g))}</li>`;
        });
        html += `</ul></div>`;
    }

    container.innerHTML = html || '<p class="empty-state">暂无周报数据</p>';
}
```

**Step 2: Commit**

```bash
git add index.html
git commit -m "feat: add frontier weekly report page"
```

---

### Task 16: 待读队列 + 研究机会 + 论文库适配

**Files:**
- Modify: `index.html`

**Step 1: 待读队列 tab**

```html
<button class="tab-btn" data-tab="readqueue">待读队列</button>
```

```javascript
function renderReadQueue() {
    const container = document.getElementById('readQueueContent');
    if (!container) return;

    // 从 papers.json 中筛选 promoted 且 relevance 高的
    const queue = (papersData.papers || [])
        .filter(p => p.role === 'promoted' && p.scores && p.scores.total >= 5)
        .sort((a, b) => (b.scores?.total || 0) - (a.scores?.total || 0))
        .slice(0, 20);

    if (!queue.length) {
        container.innerHTML = '<p class="empty-state">待读队列为空</p>';
        return;
    }

    container.innerHTML = queue.map(p => {
        const qNames = (p.question_ids || []).map(qid => {
            const q = questionsData.questions.find(q => q.id === qid);
            return q ? q.name : qid;
        });
        return `
        <div class="read-queue-item">
            <h4>${escapeHtml(p.title)}</h4>
            <p class="paper-meta">${(p.authors || []).slice(0, 3).map(a => a.name).join(', ')} · ${p.year || ''}</p>
            <p class="match-info">匹配问题: ${qNames.join(', ')} · 得分: ${(p.scores?.total || 0).toFixed(1)}</p>
            <p class="discovery-reason">${escapeHtml(p.discovery_reason || '')}</p>
        </div>`;
    }).join('');
}
```

**Step 2: 研究机会地图**

```javascript
function renderOpportunityMap() {
    const container = document.getElementById('opportunityContent');
    if (!container || !claimsData.claims.length) {
        if (container) container.innerHTML = '<p class="empty-state">暂无主张数据，无法生成研究机会地图</p>';
        return;
    }

    // 构建方法 × 验证类型矩阵
    const methods = ['LES', 'DES', 'RANS', 'CAA', 'PINN', 'experiment', 'analytical'];
    const evidenceTypes = ['numerical', 'experiment', 'analytical', 'review'];

    const matrix = {};
    methods.forEach(m => {
        matrix[m] = {};
        evidenceTypes.forEach(e => { matrix[m][e] = 0; });
    });

    claimsData.claims.forEach(c => {
        const method = (c.method || '').toLowerCase();
        const etype = (c.evidence_type || '').toLowerCase();
        methods.forEach(m => {
            if (method.includes(m.toLowerCase())) {
                evidenceTypes.forEach(e => {
                    if (etype.includes(e)) matrix[m][e]++;
                });
            }
        });
    });

    let html = '<h3>方法 × 验证类型</h3><div class="matrix-container"><table class="opportunity-matrix"><thead><tr><th></th>';
    evidenceTypes.forEach(e => { html += `<th>${e}</th>`; });
    html += '</tr></thead><tbody>';

    methods.forEach(m => {
        html += `<tr><td><strong>${m}</strong></td>`;
        evidenceTypes.forEach(e => {
            const count = matrix[m][e];
            const level = count === 0 ? 'empty' : count <= 2 ? 'sparse' : 'filled';
            html += `<td class="matrix-cell matrix-${level}">${count}</td>`;
        });
        html += '</tr>';
    });

    html += '</tbody></table></div>';
    html += '<p class="matrix-legend"><span class="matrix-empty">░░</span> 稀缺/空白 &nbsp; <span class="matrix-sparse">█░</span> 较少 &nbsp; <span class="matrix-filled">██</span> 充足</p>';

    container.innerHTML = html;
}
```

**Step 3: 论文库适配**

在论文筛选下拉框中添加"按问题筛选"选项：

```javascript
// 在现有筛选逻辑中添加
function filterByQuestion(papers, questionId) {
    if (!questionId) return papers;
    return papers.filter(p => (p.question_ids || []).includes(questionId));
}
```

**Step 4: CSS 补充**

```css
.frontier-section {
    margin: 16px 0;
    padding: 12px;
    background: var(--card-bg, #fafafa);
    border-radius: 8px;
}
.read-queue-item {
    padding: 12px;
    border-bottom: 1px solid var(--border-color, #eee);
}
.match-info {
    font-size: 0.85em;
    color: var(--primary-color, #1976d2);
}
.discovery-reason {
    font-size: 0.85em;
    color: var(--text-secondary, #888);
}
.opportunity-matrix {
    border-collapse: collapse;
    width: 100%;
}
.opportunity-matrix th, .opportunity-matrix td {
    padding: 8px 12px;
    text-align: center;
    border: 1px solid var(--border-color, #ddd);
}
.matrix-empty {
    background: #fff3e0;
    color: #e65100;
}
.matrix-sparse {
    background: #fff8e1;
    color: #f57f17;
}
.matrix-filled {
    background: #e8f5e9;
    color: #2e7d32;
}
```

**Step 5: Commit**

```bash
git add index.html
git commit -m "feat: add read queue, opportunity map, and paper library question filter"
```

---

### Task 17: 最终集成测试与清理

**Files:**
- Modify: `tests/test_all.py`
- Modify: `index.html`

**Step 1: 更新前端测试**

在 `tests/test_all.py` 的 `TestFrontend` 类中添加：

```python
def test_index_html_has_new_tabs(self):
    content = (PROJECT_ROOT / "index.html").read_text(encoding="utf-8")
    new_tabs = ["questions", "frontier", "readqueue", "opportunity"]
    for tab in new_tabs:
        assert f'data-tab="{tab}"' in content, f"缺少新 tab: {tab}"

def test_index_html_loads_new_data(self):
    content = (PROJECT_ROOT / "index.html").read_text(encoding="utf-8")
    assert "questions.json" in content
    assert "claims.json" in content
    assert "frontier.json" in content

def test_index_html_has_new_functions(self):
    content = (PROJECT_ROOT / "index.html").read_text(encoding="utf-8")
    functions = ["renderQuestionsDashboard", "renderFrontier", "renderReadQueue", "renderOpportunityMap"]
    for fn in functions:
        assert fn in content, f"前端缺少函数: {fn}"
```

**Step 2: 运行全量测试**

Run: `pytest tests/ -v`
Expected: 全部 PASS

**Step 3: Commit**

```bash
git add tests/test_all.py index.html
git commit -m "test: update frontend tests for new tabs and data loading"
```

---

## 完成检查清单

- [ ] `pytest tests/ -v` 全部通过
- [ ] `python -m scripts.main --sync-seeds` 可正常从 Zotero 同步（需配置环境变量）
- [ ] `python -m scripts.main --fetch-only` 输出到 candidates.json
- [ ] `python -m scripts.main --promote-only` 从候选中提升论文
- [ ] `python -m scripts.main --init-questions` 生成 questions.json
- [ ] `python -m scripts.main --all` 完整流水线运行无报错
- [ ] 浏览器打开 index.html 所有新 tab 可正常渲染
- [ ] 现有论文的 analysis 字段保留兼容
