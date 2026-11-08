"""反思 worker 命令行入口。

收盘后运行：
    python -m pipeline.run_reflection --dry-run   # 试运行，只统计不写记忆
    python -m pipeline.run_reflection             # 真实执行，写入 5 个记忆集合

注意：这里不再需要 TradingAgentsGraph，也不调用任何 LLM。
真实执行时只多付一次「加载 .env + 连 ChromaDB」的代价。
"""

import argparse
import logging
import sys

from pipeline.reflection_runner import ReflectionRunner


def _build_writer():
    """按需加载 TradingAgents-CN 的环境变量，建好 5 个记忆集合的写入器。

    刻意做成懒加载：试运行不该被迫导入 TradingAgents-CN、连 ChromaDB 或读 .env。
    """
    ta_path = "/home/lima/workspace/stock/TradingAgents-CN"
    if ta_path not in sys.path:
        sys.path.insert(0, ta_path)
    from dotenv import load_dotenv

    load_dotenv(f"{ta_path}/.env")
    from pipeline.reflection_writer import MemoryWriter

    return MemoryWriter()


def main() -> int:
    p = argparse.ArgumentParser(description="回填决策收益并写入记忆库")
    p.add_argument("--dry-run", action="store_true",
                   help="只统计不执行，不写记忆，不修改队列")
    p.add_argument("--backfill", action="store_true",
                   help="先把历史决策里「现在就能算出结果」的补登记到队列，再执行")
    p.add_argument("--retry-all", action="store_true",
                   help="把队列里所有条目的 fail_count 归零后再跑（embedding 服务抽风导致的"
                        "失败不该算在条目头上；不归零的话失败满 3 次的条目会被永久跳过）")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("run_reflection")

    runner = ReflectionRunner(
        dry_run=args.dry_run,
        writer=None if args.dry_run else _build_writer,
    )

    if args.retry_all:
        if args.dry_run:
            log.info("试运行模式：--retry-all 不生效（不改队列）")
        else:
            n = runner.store.reset_failures()
            log.info("已把 %d 条的失败计数归零，重新纳入重试", n)

    if args.backfill:
        from pipeline.reflection_worker import collect_backfillable

        n = collect_backfillable(runner.store, dry_run=args.dry_run)
        log.info("历史决策中可回填 %d 条%s", n, "（试运行：未登记）" if args.dry_run else "（已登记）")

    log.info("待处理任务: %d 条", len(runner.store.all_pending()))
    if args.dry_run:
        log.info("试运行模式：不会写入记忆，也不会修改队列")

    done = runner.run_once()
    log.info("本轮完成 %d 条", done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
