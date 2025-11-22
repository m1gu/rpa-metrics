from __future__ import annotations

import argparse

from src.services.pipeline import run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta el robot de METRC con un rango dinamico de dias."
    )
    parser.add_argument(
        "-d",
        "--days",
        type=int,
        default=None,
        help="Cantidad de dias hacia atras para el filtro de fechas (ej. 180).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(date_range_days=args.days)


if __name__ == "__main__":
    main()
