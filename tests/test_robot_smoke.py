from __future__ import annotations

import logging

from src.automation.robot import MetrcRobot
from src.config import settings


def test_smoke_fetch_rows():
    """Smoke test to ensure robot fetch_table_rows returns a list (may be empty without env/playwright)."""
    logging.basicConfig(level=logging.INFO)
    robot = MetrcRobot(settings.playwright)
    rows = robot.fetch_table_rows()
    assert isinstance(rows, list)

