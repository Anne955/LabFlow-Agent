from __future__ import annotations

import argparse
import csv
from pathlib import Path


def normalize_csv(input_path: Path, output_path: Path) -> None:
    with input_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        rows = [[cell.strip() for cell in row] for row in reader]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize CSV headers and cell whitespace.")
    parser.add_argument("input_path")
    parser.add_argument("output_path")
    args = parser.parse_args()
    normalize_csv(Path(args.input_path), Path(args.output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
