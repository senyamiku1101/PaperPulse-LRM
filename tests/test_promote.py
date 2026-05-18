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
        assert len(promoted) == 2
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
