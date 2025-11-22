from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Dict, Iterable, List, Mapping, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.config.settings import settings
from src.db.engine import session_scope
from src.db.models import get_table

logger = logging.getLogger(__name__)

DATE_FORMAT = "%m/%d/%Y"


def insert_rows(table_name: str, rows: Iterable[Mapping[str, object]]) -> int:
    """
    Insert only new metrc_id values; existing metrc_id rows are skipped.
    """
    table = get_table(table_name, schema=settings.database.schema)
    payloads: List[Dict[str, object]] = []
    skipped = 0
    duplicates = 0

    with session_scope() as session:
        existing_ids = {
            row[0]
            for row in session.execute(select(table.c.metrc_id))
        }

        for row in rows:
            mapped = _map_row(row)
            if mapped is None:
                skipped += 1
                continue
            if mapped["metrc_id"] in existing_ids:
                duplicates += 1
                continue
            payloads.append(mapped)

        if skipped:
            logger.warning("Skipped %d rows due to missing mandatory fields.", skipped)
        if duplicates:
            logger.info("Skipped %d rows because metrc_id already existed.", duplicates)

        if not payloads:
            logger.info("No new rows to insert into %s.", table_name)
            return 0

        insert_stmt = insert(table).values(payloads)
        stmt = insert_stmt.on_conflict_do_nothing(index_elements=["metrc_id"])

        result = session.execute(stmt)
        rowcount = result.rowcount if result is not None else 0
        logger.info("Inserted %d new rows into %s.", rowcount, table_name)
        return rowcount


def update_status(table_name: str, metrc_id: str, new_status: str) -> int:
    """
    Update metrc_status and status_fetched_at for a given metrc_id.
    """
    table = get_table(table_name, schema=settings.database.schema)
    stmt = (
        table.update()
        .where(table.c.metrc_id == metrc_id)
        .values(metrc_status=new_status, status_fetched_at=func.now())
    )
    with session_scope() as session:
        result = session.execute(stmt)
        updated = result.rowcount if result is not None else 0
        if updated:
            logger.info("Updated status for metrc_id %s to %s.", metrc_id, new_status)
        else:
            logger.warning("No rows updated for metrc_id %s.", metrc_id)
        return updated


def fetch_all_rows(table_name: str) -> List[Dict[str, object]]:
    """
    Fetch all rows (metrc_id, metrc_status, metrc_date) from the table.
    """
    table = get_table(table_name, schema=settings.database.schema)
    with session_scope() as session:
        result = session.execute(
            select(table.c.metrc_id, table.c.metrc_status, table.c.metrc_date)
        )
        return [
            {
                "metrc_id": row.metrc_id,
                "metrc_status": row.metrc_status,
                "metrc_date": row.metrc_date,
            }
            for row in result.fetchall()
        ]


def _map_row(row: Mapping[str, object]) -> Optional[Dict[str, object]]:
    metrc_id = _get_str(row.get("Tag"))
    metrc_status = _get_str(row.get("LT Status"))
    date_value = _parse_date(row.get("Date"))

    if not metrc_id or not metrc_status or date_value is None:
        logger.debug(
            "Row missing required fields: metrc_id=%s, metrc_status=%s, date=%s",
            metrc_id,
            metrc_status,
            row.get("Date"),
        )
        return None

    return {
        "metrc_id": metrc_id,
        "metrc_status": metrc_status,
        "metrc_date": date_value,
        "raw_payload": dict(row),
    }


def _get_str(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().rstrip(",").strip()
    return text or None


def _parse_date(value: object) -> Optional[date]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.split()[0]  # Drop any time component if present.
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        logger.warning("Unable to parse date '%s' with format %s", text, DATE_FORMAT)
        return None


__all__ = ["insert_rows", "update_status", "fetch_all_rows"]

