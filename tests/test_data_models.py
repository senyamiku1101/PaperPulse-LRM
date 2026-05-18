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
