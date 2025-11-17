from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime
from typing import Dict, Iterable, List, Mapping, Optional

from sqlalchemy import Column, Date, DateTime, Integer, MetaData, String, Table, create_engine, func
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
    Persist rows into PostgreSQL using an UPSERT on (metrc_id, metrc_date, metrc_status).
    """
    table = _get_table(table_name)
    payloads: List[Dict[str, object]] = []
    skipped = 0

    for row in rows:
        mapped = _map_row(row)
        if mapped is None:
            skipped += 1
            continue
        payloads.append(mapped)

    if skipped:
        logger.warning("Skipped %d rows due to missing mandatory fields.", skipped)

    if not payloads:
        logger.info("No valid rows to persist.")
        return 0

    insert_stmt = insert(table).values(payloads)
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=["metrc_id", "metrc_date", "metrc_status"],
        set_={
            "raw_payload": insert_stmt.excluded.raw_payload,
            "status_fetched_at": func.now(),
        },
    )

    with session_scope() as session:
        session.execute(stmt)
        rowcount = len(payloads)
        logger.info("Persisted %d rows into %s.", rowcount, table_name)
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
    text = str(value).strip()
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
