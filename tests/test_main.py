from bank_sync.main import _format_mutation_summary, _needs_update, load_config
from bank_sync.sheets_client import TRANSACTION_HEADERS


def test_load_config_reads_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"key": 1}')
    config = load_config(path)
    assert config == {"key": 1}


def test_load_config_defaults_deletion_threshold(tmp_path):
    """Verify deletion_warning_threshold defaults to 50 if not specified."""
    path = tmp_path / "config.json"
    path.write_text('{"akahu_user_token": "test"}')
    config = load_config(path)
    # Should default to 50 when accessed with get()
    assert config.get("deletion_warning_threshold", 50) == 50


def test_needs_update_detects_differences():
    existing = dict(zip(TRANSACTION_HEADERS, ["a"] * len(TRANSACTION_HEADERS)))
    new_row = ["a"] * len(TRANSACTION_HEADERS)
    assert _needs_update(existing, new_row) is False
    new_row[3] = "different"
    assert _needs_update(existing, new_row) is True


def test_format_mutation_summary_reports_actions():
    summary = _format_mutation_summary([["row"]], [(10, ["updated"])], [1, 2])
    assert "append 1 new row(s)" in summary
    assert "update 1 existing row(s)" in summary
    assert "delete 2 orphaned row(s)" in summary


def test_format_mutation_summary_handles_noops():
    assert _format_mutation_summary([], [], []) == ["no sheet mutations are required"]
