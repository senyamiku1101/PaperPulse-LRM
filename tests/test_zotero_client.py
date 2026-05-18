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
        with patch("scripts.zotero_client.ZOTERO_USER_ID", ""), \
             patch("scripts.zotero_client.ZOTERO_API_KEY", ""):
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
        all_data = [
            {"key": "ABC123", "data": {"name": "宽频噪声", "parentCollection": False}},
            {"key": "DEF456", "data": {"name": "声衬设计", "parentCollection": False}},
            {"key": "GHI789", "data": {"name": "子集合", "parentCollection": "ABC123"}},
        ]
        call_count = {"n": 0}
        def mock_get(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if call_count["n"] == 0:
                resp.json.return_value = all_data
            else:
                resp.json.return_value = []
            call_count["n"] += 1
            return resp
        client.session.get = mock_get

        cols = client.get_collections(filter_names=["宽频噪声"])
        # 匹配"宽频噪声"后展开为叶子集合"子集合"
        assert len(cols) == 1
        assert cols[0]["key"] == "GHI789"
        assert cols[0]["_matched_parent"] == "宽频噪声"

    def test_get_collections_all_top_level(self):
        """filter_names 为空时返回所有顶层集合"""
        from scripts.zotero_client import ZoteroClient
        client = ZoteroClient(user_id="12345", api_key="test-key")
        all_data = [
            {"key": "ABC123", "data": {"name": "宽频噪声", "parentCollection": False}},
            {"key": "DEF456", "data": {"name": "声衬设计", "parentCollection": False}},
            {"key": "GHI789", "data": {"name": "子集合", "parentCollection": "ABC123"}},
        ]
        call_count = {"n": 0}
        def mock_get(*args, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if call_count["n"] == 0:
                resp.json.return_value = all_data
            else:
                resp.json.return_value = []
            call_count["n"] += 1
            return resp
        client.session.get = mock_get

        cols = client.get_collections(filter_names=[])
        assert len(cols) == 2
