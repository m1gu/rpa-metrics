from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterable

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from src.config.settings import DatabaseSettings, settings

logger = logging.getLogger(__name__)


def _build_engine(config: DatabaseSettings) -> Engine:
    return create_engine(
        config.dsn,
        future=True,
        pool_pre_ping=True,
    )


engine = _build_engine(settings.database)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


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


__all__ = ["engine", "session_scope", "_build_engine"]

