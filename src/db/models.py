from __future__ import annotations

from typing import Dict

from sqlalchemy import Column, Date, DateTime, Integer, MetaData, String, Table
from sqlalchemy.dialects.postgresql import JSONB

from src.config.settings import settings

metadata = MetaData()
_table_cache: Dict[str, Table] = {}


def get_table(table_name: str, *, schema: str | None = None) -> Table:
    """
    Lazily create and cache a Table definition for the target schema.
    """
    table_schema = schema or settings.database.schema
    cache_key = f"{table_schema}.{table_name}"
    if cache_key not in _table_cache:
        _table_cache[cache_key] = Table(
            table_name,
            metadata,
            Column("id", Integer, primary_key=True),
            Column("metrc_id", String(255), nullable=False),
            Column("metrc_status", String(64), nullable=False),
            Column("metrc_date", Date, nullable=False),
            Column("status_fetched_at", DateTime(timezone=True)),
            Column("raw_payload", JSONB),
            schema=table_schema,
            extend_existing=True,
        )
    return _table_cache[cache_key]


__all__ = ["get_table", "metadata"]

