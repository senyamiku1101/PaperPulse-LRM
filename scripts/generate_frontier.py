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

    recent_papers = [p for p in papers if p.get("role") == "promoted"]
    recent_claims = claims[-20:]

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
                               '以JSON格式返回：{"summary": "...", "key_findings": [...], "trends": [...], "gaps": [...], "recommended_reads": [...]}'
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
