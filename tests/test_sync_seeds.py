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
        a_entry = next(e for e in result if e["doi"] == "10.1234/a")
        assert a_entry["zotero_collections"] == ["col1"]
        b_entry = next(e for e in result if e["doi"] == "10.5678/b")
        assert b_entry["zotero_collections"] == ["col2"]
        assert b_entry["synced_at"] == "2026-05-18"

    def test_merge_deduplicates(self):
        """同一 DOI 出现在多个集合中应合并集合列表"""
        from scripts.sync_seeds import merge_dois

        existing = []
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
