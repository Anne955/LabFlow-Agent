from __future__ import annotations

import argparse
import csv
import re
import shutil
from pathlib import Path

METADATA_FIELDS = [
    "sample_id",
    "method",
    "instrument",
    "operator",
    "file_path",
    "source_dataset",
    "source_id",
]
NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
SOURCE_ID_RE = re.compile(r"R\d{5,}", re.IGNORECASE)


def parse_rruff_txt(path: Path, min_points: int = 10) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        numbers = NUMBER_RE.findall(stripped.replace(",", " ").replace("\t", " "))
        if len(numbers) < 2:
            continue
        try:
            x = float(numbers[0])
            intensity = float(numbers[1])
        except ValueError:
            continue
        points.append((x, intensity))
    deduped = {}
    for x, intensity in points:
        deduped[x] = intensity
    ordered = sorted(deduped.items(), key=lambda item: item[0])
    if len(ordered) < min_points:
        raise ValueError(f"{path} has only {len(ordered)} usable numeric points; need {min_points}")
    return ordered


def source_id_from_path(path: Path) -> str:
    match = SOURCE_ID_RE.search(path.stem)
    return match.group(0).upper() if match else path.stem


def write_spectrum_csv(path: Path, points: list[tuple[float, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["x", "intensity"])
        writer.writerows(points)


def write_metadata(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=METADATA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def convert_rruff_batch(
    input_dir: Path,
    output_dir: Path,
    batch_id: str,
    limit: int = 20,
    min_points: int = 10,
    instrument: str = "RRUFF public Raman export",
    operator: str = "public_fixture_converter",
    source_dataset: str = "RRUFF Raman public database",
    overwrite: bool = True,
) -> dict[str, object]:
    if not input_dir.is_dir():
        raise ValueError(f"input directory not found: {input_dir}")
    txt_files = sorted(input_dir.glob("*.txt"))
    converted: list[tuple[Path, list[tuple[float, float]]]] = []
    skipped: list[str] = []
    for raw_path in txt_files:
        try:
            points = parse_rruff_txt(raw_path, min_points=min_points)
        except ValueError as exc:
            skipped.append(str(exc))
            continue
        converted.append((raw_path, points))
        if len(converted) >= limit:
            break
    if len(converted) < limit:
        raise ValueError(f"found {len(converted)} usable spectra in {input_dir}; need {limit}")
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    spectra_dir = output_dir / "spectra"
    spectra_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    for index, (raw_path, points) in enumerate(converted, start=1):
        sample_id = f"rruff_{index:03d}"
        relative_file = f"spectra/{sample_id}_raman.csv"
        write_spectrum_csv(output_dir / relative_file, points)
        rows.append(
            {
                "sample_id": sample_id,
                "method": "raman",
                "instrument": instrument,
                "operator": operator,
                "file_path": relative_file,
                "source_dataset": source_dataset,
                "source_id": source_id_from_path(raw_path),
            }
        )
    write_metadata(output_dir / "metadata.csv", rows)
    log = [
        f"Instrument: {instrument}",
        f"Batch: {batch_id}",
        f"Source dataset: {source_dataset}",
        "Conversion script: scripts/convert_rruff_to_labflow_csv.py",
        "Purpose: LabFlow compatibility validation only; not scientific accuracy validation.",
        f"Raw input directory: {input_dir.as_posix()}",
        f"Converted spectra count: {len(rows)}",
        f"Skipped raw files: {len(skipped)}",
    ]
    (output_dir / "instrument_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    return {"batch_id": batch_id, "converted": len(rows), "skipped": len(skipped), "output_dir": output_dir.as_posix()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert local RRUFF Raman txt files to a LabFlow batch.")
    parser.add_argument("--input-dir", default="data_public/rruff_raw")
    parser.add_argument("--output-dir", default="data/batch_public_rruff_001")
    parser.add_argument("--batch-id", default="batch_public_rruff_001")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-points", type=int, default=10)
    parser.add_argument("--instrument", default="RRUFF public Raman export")
    parser.add_argument("--operator", default="public_fixture_converter")
    parser.add_argument("--source-dataset", default="RRUFF Raman public database")
    parser.add_argument("--no-overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = convert_rruff_batch(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        batch_id=args.batch_id,
        limit=args.limit,
        min_points=args.min_points,
        instrument=args.instrument,
        operator=args.operator,
        source_dataset=args.source_dataset,
        overwrite=not args.no_overwrite,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
