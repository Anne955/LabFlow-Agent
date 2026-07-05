from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from pathlib import Path
from typing import Any

ANOMALIES = [
    "missing_metadata_value",
    "duplicate_sample_id",
    "missing_spectra_file",
    "file_without_metadata",
    "invalid_filename",
    "missing_spectrum_column",
    "negative_intensity",
    "x_not_monotonic",
    "too_few_points",
    "extreme_intensity",
]


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def spectrum_rows(
    base: int,
    *,
    negative: bool = False,
    non_monotonic: bool = False,
    too_few: bool = False,
    extreme: bool = False,
) -> list[dict[str, object]]:
    count = 3 if too_few else 12
    rows = []
    for idx in range(1, count + 1):
        x = idx
        if non_monotonic and idx == 4:
            x = 2
        intensity = base + idx
        if negative and idx == 3:
            intensity = -5
        if extreme and idx == 8:
            intensity = 100000
        rows.append({"x": x, "intensity": intensity})
    return rows


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def generate_batch(
    root: Path, batch_index: int, samples_per_batch: int, rng: random.Random
) -> dict[str, Any]:
    batch_id = f"batch_demo_{batch_index:03d}"
    batch_dir = root / "data" / batch_id
    labels_dir = root / "labels"
    if batch_dir.exists():
        shutil.rmtree(batch_dir)
    batch_dir.mkdir(parents=True)
    spectra_dir = batch_dir / "spectra"
    spectra_dir.mkdir()
    labels_dir.mkdir(exist_ok=True)

    metadata_rows: list[dict[str, object]] = []
    expected: list[dict[str, object]] = []
    for idx in range(1, samples_per_batch + 1):
        sample_id = f"sample_{idx:03d}"
        operator = chr(ord("A") + ((idx + batch_index) % 5))
        if idx == 3:
            operator = ""
            expected.append(
                {
                    "sample_id": sample_id,
                    "check": "missing_metadata_value",
                    "severity": "warning",
                    "source": "metadata.csv",
                    "description": "operator is missing",
                }
            )
        metadata_rows.append(
            {
                "sample_id": sample_id,
                "method": "raman",
                "operator": operator,
                "condition": rng.choice(["control", "test"]),
            }
        )
    duplicate_id = "sample_004"
    metadata_rows.append(
        {"sample_id": duplicate_id, "method": "raman", "operator": "B", "condition": "duplicate"}
    )
    expected.append(
        {
            "sample_id": duplicate_id,
            "check": "duplicate_sample_id",
            "severity": "critical",
            "source": "metadata.csv",
            "description": "duplicate sample id",
        }
    )
    write_csv(
        batch_dir / "metadata.csv", metadata_rows, ["sample_id", "method", "operator", "condition"]
    )

    for idx in range(1, samples_per_batch + 1):
        sample_id = f"sample_{idx:03d}"
        if idx == 6:
            expected.append(
                {
                    "sample_id": sample_id,
                    "check": "missing_spectra_file",
                    "severity": "critical",
                    "source": "spectra",
                    "description": "metadata sample has no spectra file",
                }
            )
            continue
        path = spectra_dir / f"{sample_id}_raman.csv"
        if idx == 7:
            write_csv(path, [{"x": i} for i in range(1, 13)], ["x"])
            expected.append(
                {
                    "sample_id": sample_id,
                    "check": "missing_spectrum_column",
                    "severity": "critical",
                    "source": path.relative_to(root).as_posix(),
                    "description": "missing intensity column",
                }
            )
        else:
            rows = spectrum_rows(
                100 + batch_index * 10 + idx,
                negative=idx == 8,
                non_monotonic=idx == 9,
                too_few=idx == 10,
                extreme=idx == 11,
            )
            write_csv(path, rows, ["x", "intensity"])
            if idx == 8:
                expected.append(
                    {
                        "sample_id": sample_id,
                        "check": "negative_intensity",
                        "severity": "critical",
                        "source": path.relative_to(root).as_posix(),
                        "description": "negative intensity",
                    }
                )
            if idx == 9:
                expected.append(
                    {
                        "sample_id": sample_id,
                        "check": "x_not_monotonic",
                        "severity": "critical",
                        "source": path.relative_to(root).as_posix(),
                        "description": "x is not strictly increasing",
                    }
                )
            if idx == 10:
                expected.append(
                    {
                        "sample_id": sample_id,
                        "check": "too_few_points",
                        "severity": "warning",
                        "source": path.relative_to(root).as_posix(),
                        "description": "too few points",
                    }
                )
            if idx == 11:
                expected.append(
                    {
                        "sample_id": sample_id,
                        "check": "extreme_intensity",
                        "severity": "warning",
                        "source": path.relative_to(root).as_posix(),
                        "description": "extreme intensity outlier",
                    }
                )

    orphan = spectra_dir / "sample_021_raman.csv"
    write_csv(orphan, spectrum_rows(200), ["x", "intensity"])
    expected.append(
        {
            "sample_id": "sample_021",
            "check": "file_without_metadata",
            "severity": "critical",
            "source": orphan.relative_to(root).as_posix(),
            "description": "orphan spectra file",
        }
    )
    bad = spectra_dir / "badname.csv"
    write_csv(bad, spectrum_rows(210), ["x", "intensity"])
    expected.append(
        {
            "sample_id": "badname",
            "check": "invalid_filename",
            "severity": "warning",
            "source": bad.relative_to(root).as_posix(),
            "description": "invalid filename",
        }
    )
    expected.append(
        {
            "sample_id": "badname",
            "check": "file_without_metadata",
            "severity": "critical",
            "source": bad.relative_to(root).as_posix(),
            "description": "invalid filename also has no metadata record",
        }
    )

    (batch_dir / "instrument_log.txt").write_text(
        (
            f"Instrument: Demo Raman\n"
            f"Batch: {batch_id}\n"
            f"Seeded anomalies: {', '.join(sorted({item['check'] for item in expected}))}\n"
        ),
        encoding="utf-8",
    )
    manifest = []
    for path in sorted(batch_dir.rglob("*")):
        if path.is_file():
            manifest.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": file_sha256(path),
                    "size": path.stat().st_size,
                }
            )
    payload = {
        "batch_id": batch_id,
        "expected_findings": expected,
        "labels": expected,
        "raw_data_manifest": manifest,
    }
    (labels_dir / f"{batch_id}_labels.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic LabFlow demo batches.")
    parser.add_argument("--batches", type=int, default=5)
    parser.add_argument("--samples-per-batch", "--samples", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    rng = random.Random(args.seed)
    generated = [
        generate_batch(root, index, args.samples_per_batch, rng)
        for index in range(1, args.batches + 1)
    ]
    print(
        json.dumps(
            {
                "batches": len(generated),
                "expected_findings": sum(len(item["expected_findings"]) for item in generated),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
