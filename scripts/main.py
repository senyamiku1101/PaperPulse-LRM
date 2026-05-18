"""PaperPulse 主入口 - 编排所有数据处理流程"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.config import DATA_DIR

logger = logging.getLogger("paperpulse")


def setup_logging():
    """配置日志输出到控制台和文件"""
    DATA_DIR.mkdir(exist_ok=True)
    log_file = DATA_DIR.parent / "scripts" / "update.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    # 文件
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def run_fetch():
    """运行论文抓取"""
    logger.info("=== 开始引用图谱抓取 ===")
    start = time.time()
    from scripts.fetch_papers import fetch_citation_graph
    fetch_citation_graph()
    logger.info(f"引用图谱抓取完成，耗时 {time.time()-start:.1f}s")


def run_analyze():
    """运行 AI 分析"""
    logger.info("=== 开始 AI 分析 ===")
    start = time.time()
    from scripts.analyze_papers import analyze_unanalyzed_papers
    analyze_unanalyzed_papers()
    logger.info(f"AI 分析完成，耗时 {time.time()-start:.1f}s")


def run_groups():
    """运行课题组自动发现"""
    logger.info("=== 开始课题组自动发现 ===")
    start = time.time()
    from scripts.discover_groups import discover_groups
    discover_groups()
    logger.info(f"课题组自动发现完成，耗时 {time.time()-start:.1f}s")


def run_trends():
    """生成趋势数据"""
    logger.info("=== 开始趋势数据生成 ===")
    start = time.time()
    from scripts.generate_trends import generate_trend_data
    generate_trend_data()
    logger.info(f"趋势数据生成完成，耗时 {time.time()-start:.1f}s")


def run_summary():
    """生成汇总统计"""
    logger.info("=== 开始汇总统计生成 ===")
    start = time.time()
    from scripts.generate_summary import generate_summary
    generate_summary()
    logger.info(f"汇总统计生成完成，耗时 {time.time()-start:.1f}s")


def run_sync_seeds():
    """从 Zotero 同步种子 DOI"""
    logger.info("=== 开始 Zotero 种子同步 ===")
    start = time.time()
    from scripts.sync_seeds import sync_from_zotero
    new_count = sync_from_zotero()
    logger.info(f"Zotero 种子同步完成，新增 {new_count} 个，耗时 {time.time()-start:.1f}s")


def run_promote():
    """运行候选提升"""
    logger.info("=== 开始候选提升 ===")
    start = time.time()
    from scripts.promote import run_promotion
    count = run_promotion()
    logger.info(f"候选提升完成，提升 {count} 篇，耗时 {time.time()-start:.1f}s")


def run_init_questions():
    """初始化问题图谱"""
    logger.info("=== 开始问题图谱初始化 ===")
    start = time.time()
    from scripts.init_questions import init_questions
    init_questions(force=True)
    logger.info(f"问题图谱初始化完成，耗时 {time.time()-start:.1f}s")


def run_frontier():
    """生成前沿差异报告"""
    logger.info("=== 开始前沿差异生成 ===")
    start = time.time()
    from scripts.generate_frontier import generate_frontier_report
    generate_frontier_report()
    logger.info(f"前沿差异生成完成，耗时 {time.time()-start:.1f}s")


def run_clear(confirm: bool = False):
    """清空 data/ 目录下的所有 JSON 文件"""
    json_files = list(DATA_DIR.glob("*.json"))
    if not json_files:
        logger.info("data/ 目录下没有 JSON 文件，无需清理")
        return

    if not confirm:
        logger.warning("--clear 需要配合 --yes 确认，例如: python -m scripts.main --clear --yes")
        sys.exit(0)

    for f in json_files:
        f.unlink()
        logger.info(f"已删除: {f.name}")

    logger.info(f"清空完成，共删除 {len(json_files)} 个文件")


def main():
    parser = argparse.ArgumentParser(description="PaperPulse 数据更新工具")
    parser.add_argument("--all", action="store_true", help="运行所有步骤（默认）")
    parser.add_argument("--fetch-only", action="store_true", help="仅抓取论文")
    parser.add_argument("--analyze-only", action="store_true", help="仅 AI 分析")
    parser.add_argument("--trends-only", action="store_true", help="仅生成趋势数据")
    parser.add_argument("--groups-only", action="store_true", help="仅追踪课题组")
    parser.add_argument("--summary-only", action="store_true", help="仅生成汇总")
    parser.add_argument("--sync-seeds", action="store_true", help="从 Zotero 同步种子 DOI")
    parser.add_argument("--promote-only", action="store_true", help="仅提升候选论文")
    parser.add_argument("--init-questions", action="store_true", help="强制重新初始化问题图谱")
    parser.add_argument("--clear", action="store_true", help="清空 data/ 目录下的所有 JSON 文件")
    parser.add_argument("--yes", "-y", action="store_true", help="确认执行破坏性操作（配合 --clear 使用）")

    args = parser.parse_args()

    # 默认运行全部
    run_all = args.all or not any([
        args.sync_seeds, args.fetch_only, args.promote_only, args.analyze_only,
        args.trends_only, args.groups_only, args.summary_only, args.init_questions,
    ])

    setup_logging()

    # 清空数据库
    if args.clear:
        run_clear(confirm=args.yes)
        return

    logger.info(f"PaperPulse 更新开始 - {datetime.now(timezone.utc).isoformat()}")
    total_start = time.time()

    try:
        if run_all or args.sync_seeds:
            run_sync_seeds()

        # 自动初始化问题图谱（如果还没有问题）
        if args.init_questions:
            run_init_questions()
        elif run_all:
            from scripts.data_models import load_or_create
            q_data = load_or_create(DATA_DIR / "questions.json", "questions")
            if not q_data.get("questions"):
                logger.info("问题图谱为空，自动初始化")
                run_init_questions()

        if run_all or args.fetch_only:
            run_fetch()
        if run_all or args.promote_only:
            run_promote()
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
        if run_all or args.trends_only:
            run_trends()
        if run_all or args.summary_only:
            run_summary()
    except Exception as e:
        logger.error(f"更新失败: {e}", exc_info=True)
        sys.exit(1)

    logger.info(f"PaperPulse 更新完成，总耗时 {time.time()-total_start:.1f}s")


if __name__ == "__main__":
    main()
