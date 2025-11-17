from __future__ import annotations

import logging
import sys

from config import settings
from robot import MetrcRobot


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    robot = MetrcRobot(settings.playwright)
    rows = robot.fetch_table_rows()
    if not rows:
        print("No se encontraron registros despues de aplicar los filtros.")
        return
    first_tag = rows[0].get("Tag") or "<empty>"
    print(f"Primer Tag despues de filtrar 'pro': {first_tag}")


if __name__ == "__main__":
    main()
