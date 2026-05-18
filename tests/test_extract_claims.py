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
