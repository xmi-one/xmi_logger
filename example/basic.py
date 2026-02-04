import asyncio
import os
import sys
from datetime import datetime

# sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from xmi_logger import XmiLogger


def run_basic() -> None:
    log_dir = os.path.join(os.path.dirname(__file__), "logs_basic")
    logger = XmiLogger(
        file_name="basic",
        log_dir=log_dir,
        language="zh",
        enable_stats=True,
        rotation_time="1 day",
        compression="zip",
    )

    token = logger.request_id_var.set("req-basic-001")
    try:
        logger.info("基础日志: info")
        logger.warning("基础日志: warning")
        logger.error("基础日志: error")

        logger.log_with_tag("INFO", "带 tag 的日志", tag="BOOT")
        logger.log_with_category("INFO", "带 category 的日志", category="SYSTEM")
        logger.log_with_location("INFO", "带位置信息的日志")

        logger.log_with_context("INFO", "带上下文的日志", {"user_id": 123, "path": "/api/demo"})
        logger.log_with_timing("INFO", "带计时信息的日志", {"db": 0.023, "total": 0.081})
    finally:
        logger.request_id_var.reset(token)

    logger.batch_log(
        [
            {"level": "INFO", "message": "batch-1", "tag": "BATCH"},
            {"level": "WARNING", "message": "batch-2", "category": "SYSTEM"},
            {"level": "ERROR", "message": "batch-3"},
        ]
    )

    print("stats:", logger.get_stats())
    print("summary:", logger.get_stats_summary())
    print("performance_stats:", logger.get_performance_stats())
    logger.cleanup()


async def run_async_decorator() -> None:
    log_dir = os.path.join(os.path.dirname(__file__), "logs_basic")
    logger = XmiLogger(file_name="basic_async", log_dir=log_dir, language="zh", enable_stats=True)

    @logger.log_decorator()
    async def async_work(n: int) -> str:
        await asyncio.sleep(0.05)
        return f"done-{n}"

    async def handle(req_id: str, n: int) -> None:
        token = logger.request_id_var.set(req_id)
        try:
            result = await async_work(n)
            logger.info(f"async result: {result}")
        finally:
            logger.request_id_var.reset(token)

    await asyncio.gather(handle("req-a", 1), handle("req-b", 2))
    logger.cleanup()


def main() -> None:
    run_basic()
    asyncio.run(run_async_decorator())
    print("basic example finished at", datetime.now().isoformat(timespec="seconds"))


if __name__ == "__main__":
    main()
