from __future__ import annotations

import argparse

from main import run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta el robot de METRC con un rango dinámico de días."
    )
    parser.add_argument(
        "-d",
        "--days",
        type=int,
        default=None,
        help="Cantidad de días hacia atrás para el filtro de fechas (ej. 180).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run(date_range_days=args.days)


if __name__ == "__main__":
    main()
