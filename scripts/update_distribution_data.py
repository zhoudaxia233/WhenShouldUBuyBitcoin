#!/usr/bin/env python3
"""
Refresh the bundled BitInfoCharts wealth distribution fallback.

This intentionally updates only dca_service/src/dca_service/data/wealth_distribution.json.
It does not run main.py and does not regenerate docs/data or docs/charts.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DCA_SRC = PROJECT_ROOT / "dca_service" / "src"
if str(DCA_SRC) not in sys.path:
    sys.path.insert(0, str(DCA_SRC))

from dca_service.services.distribution_scraper import fetch_distribution  # noqa: E402


DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "dca_service" / "src" / "dca_service" / "data" / "wealth_distribution.json"
)


def write_distribution_snapshot(output_path: Path = DEFAULT_OUTPUT_PATH) -> Path:
    """Fetch live BitInfoCharts distribution data and atomically write the fallback JSON."""
    distribution_data = fetch_distribution(
        use_cache=False,
        allow_static_fallback=False,
        allow_stale_cache=False,
    )
    if not distribution_data:
        raise ValueError("No distribution data returned")

    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(distribution_data, tmp, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)

    tmp_path.replace(output_path)
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh only the bundled wealth distribution fallback JSON."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Output JSON path. Defaults to {DEFAULT_OUTPUT_PATH}",
    )
    args = parser.parse_args(argv)

    try:
        written_path = write_distribution_snapshot(args.output)
    except Exception as exc:
        print(f"Failed to update wealth distribution: {exc}", file=sys.stderr)
        return 1

    print(f"Updated wealth distribution snapshot: {written_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
