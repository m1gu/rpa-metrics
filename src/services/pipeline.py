from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Mapping, Optional

from src.automation.robot import MetrcRobot
from src.config import settings
from src.db import fetch_all_rows, insert_rows, update_status
from src.logging_conf import configure_logging


def run(date_range_days: Optional[int] = None) -> None:
    configure_logging(settings.runtime.log_level)
    logger = logging.getLogger(__name__)
    robot = MetrcRobot(
        settings.playwright,
        date_range_days=date_range_days or settings.runtime.date_range_days,
    )
    try:
        rows: List[Mapping[str, object]] = robot.fetch_table_rows()
        logger.info("Robot extracted %d rows (post date + TestingInProgress filters)", len(rows))

        inserted = insert_rows(settings.database.table, rows) if rows else 0
        if inserted:
            logger.info("Routine 1: upserted %d rows into DB.", inserted)
        else:
            logger.warning("Routine 1: no new rows persisted.")

        db_records = fetch_all_rows(settings.database.table)
        if db_records:
            today = datetime.now(timezone.utc).date()
            start_date = today - timedelta(days=robot.date_range_days)
            in_range = [
                r
                for r in db_records
                if r.get("metrc_date") is not None and start_date <= r["metrc_date"] <= today
            ]
            records_for_verification = [
                {"Tag": r["metrc_id"], "LT Status": r["metrc_status"]}
                for r in in_range
            ]
            logger.info(
                "Routine 2: checking %d records in date range %s - %s (of %d in DB).",
                len(records_for_verification),
                start_date,
                today,
                len(db_records),
            )
            updates = robot.verify_status_by_tag(records_for_verification)
            changed = 0
            for outcome in updates:
                if outcome.get("success") and outcome.get("fetched_status") is not None:
                    if outcome["changed"]:
                        update_status(
                            settings.database.table,
                            outcome["metrc_id"],
                            outcome["fetched_status"],
                        )
                        changed += 1
                else:
                    logger.error(
                        "Routine 2: Tag %s failed after %d attempts.",
                        outcome.get("metrc_id"),
                        outcome.get("attempts"),
                    )
            if changed:
                logger.info("Routine 2: updated %d rows in DB.", changed)
            else:
                logger.info("Routine 2: no status changes detected.")
        else:
            logger.info("Routine 2: skipped (no rows from routine 1).")
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unhandled error during robot execution: %s", exc)
        raise


__all__ = ["run"]

