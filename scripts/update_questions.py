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

        claims_text = "\n".join(
            f"- [{c.get('evidence_type', '?')}] {c.get('statement', '')} "
            f"(方法: {c.get('method', '?')}, 结果: {c.get('outcome', '?')})"
            for c in q_claims[:20]
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
