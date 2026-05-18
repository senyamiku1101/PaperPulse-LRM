"""廉价评分模块测试"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def make_paper(**kwargs):
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
        assert score > 0
        assert score <= 5

    def test_seed_connections_multi_bonus(self):
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
        assert result["total"] <= 14
