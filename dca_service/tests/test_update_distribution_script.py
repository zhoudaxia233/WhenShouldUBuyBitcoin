"""Tests for the local wealth distribution refresh script."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "update_distribution_data.py"
spec = importlib.util.spec_from_file_location("update_distribution_data", SCRIPT_PATH)
update_distribution_data = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(update_distribution_data)


def test_update_distribution_script_writes_only_requested_snapshot(tmp_path: Path):
    """The local refresh command should update only the bundled fallback JSON."""
    output_path = tmp_path / "wealth_distribution.json"
    sample_distribution = [
        {
            "tier": "[1 - 10)",
            "balance": "[1 - 10)",
            "addresses": "200000",
            "coins": "500000",
            "usd": "$38200000000",
            "percent_coins": "2.50%",
            "percentile": "Top 1.66%",
        }
    ]

    with patch.object(
        update_distribution_data,
        "fetch_distribution",
        return_value=sample_distribution,
    ) as mock_fetch:
        written_path = update_distribution_data.write_distribution_snapshot(output_path)

    assert written_path == output_path
    assert json.loads(output_path.read_text(encoding="utf-8")) == sample_distribution
    mock_fetch.assert_called_once_with(
        use_cache=False,
        allow_static_fallback=False,
        allow_stale_cache=False,
    )


def test_update_distribution_script_returns_failure_for_empty_data(tmp_path: Path):
    """An empty scrape should fail without creating a misleading snapshot."""
    output_path = tmp_path / "wealth_distribution.json"

    with patch.object(update_distribution_data, "fetch_distribution", return_value=[]):
        exit_code = update_distribution_data.main(["--output", str(output_path)])

    assert exit_code == 1
    assert not output_path.exists()
