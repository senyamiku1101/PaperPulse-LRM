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
        from scripts.init_questions import build_seed_info_text
        seeds = [
            {"doi": "10.1234/a", "zotero_collections": ["宽频噪声"]},
            {"doi": "10.5678/b", "zotero_collections": ["声衬设计"]},
        ]
        papers_by_doi = {
            "10.1234/a": {"title": "Fan broadband noise", "abstract": "LES study..."},
            "10.5678/b": {"title": "Liner design", "abstract": "Acoustic liner..."},
        }
        text = build_seed_info_text(seeds, papers_by_doi)
        assert "宽频噪声" in text
        assert "Fan broadband noise" in text
        assert "声衬设计" in text

    def test_build_seed_info_grouped_by_collection(self):
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
        idx1 = text.index("col1")
        idx2 = text.index("col2")
        assert idx1 < idx2

    def test_parse_questions_response_valid(self):
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
