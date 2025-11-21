from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime
from typing import Dict, Iterable, List, Mapping, Optional

from sqlalchemy import Column, Date, DateTime, Integer, MetaData, String, Table, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from config import DatabaseSettings, settings

logger = logging.getLogger(__name__)

DATE_FORMAT = "%m/%d/%Y"


def _build_engine(config: DatabaseSettings) -> Engine:
    return create_engine(
        config.dsn,
        future=True,
        pool_pre_ping=True,
    )


engine = _build_engine(settings.database)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
metadata = MetaData()
_table_cache: Dict[str, Table] = {}


def _get_table(table_name: str) -> Table:
    if table_name not in _table_cache:
        _table_cache[table_name] = Table(
            table_name,
            metadata,
            Column("id", Integer, primary_key=True),
            Column("metrc_id", String(255), nullable=False),
            Column("metrc_status", String(64), nullable=False),
            Column("metrc_date", Date, nullable=False),
            Column("status_fetched_at", DateTime(timezone=True)),
            Column("raw_payload", JSONB),
            schema=settings.database.schema,
            extend_existing=True,
        )
    return _table_cache[table_name]


@contextmanager
def session_scope() -> Iterable[Session]:
    """Provide a transactional scope for DB work."""
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Database error, rolled back session")
        raise
    finally:
        session.close()


def insert_rows(table_name: str, rows: Iterable[Mapping[str, object]]) -> int:
    """
    Insert only new metrc_id values; existing metrc_id rows are skipped.
    """
    table = _get_table(table_name)
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
    # Normalize whitespace and drop trailing commas often present in scraped cells.
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


def update_status(table_name: str, metrc_id: str, new_status: str) -> int:
    """
    Update metrc_status and status_fetched_at for a given metrc_id.
    """
    table = _get_table(table_name)
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
    table = _get_table(table_name)
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
