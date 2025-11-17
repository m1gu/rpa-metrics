from __future__ import annotations

import logging
import sys
from typing import List, Mapping, Optional

from config import settings
from db import insert_rows
from robot import MetrcRobot


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.runtime.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def run(date_range_days: Optional[int] = None) -> None:
    configure_logging()
    logger = logging.getLogger("main")
    robot = MetrcRobot(
        settings.playwright,
        date_range_days=date_range_days or settings.runtime.date_range_days,
    )
    try:
        rows: List[Mapping[str, object]] = robot.fetch_table_rows()
        logger.info("Robot extracted %d rows", len(rows))
        if rows:
            insert_rows(settings.database.table, rows)
        else:
            logger.warning("No rows to persist, skipping database insert.")
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unhandled error during robot execution: %s", exc)
        raise


if __name__ == "__main__":
    run()
