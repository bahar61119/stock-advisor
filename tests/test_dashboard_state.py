from stock_advisor.reporting.dashboard_state import read_dashboard_url, write_dashboard_url


def test_read_returns_none_when_no_state_file_exists(tmp_path):
    path = str(tmp_path / "does_not_exist.txt")
    assert read_dashboard_url(path) is None


def test_write_then_read_round_trips(tmp_path):
    path = str(tmp_path / "nested" / "dashboard_url.txt")
    write_dashboard_url("https://claude.ai/artifact/abc123", path)
    assert read_dashboard_url(path) == "https://claude.ai/artifact/abc123"


def test_write_creates_parent_directories(tmp_path):
    path = str(tmp_path / "a" / "b" / "c" / "dashboard_url.txt")
    write_dashboard_url("https://claude.ai/artifact/xyz", path)
    assert read_dashboard_url(path) == "https://claude.ai/artifact/xyz"


def test_write_overwrites_previous_url(tmp_path):
    path = str(tmp_path / "dashboard_url.txt")
    write_dashboard_url("https://claude.ai/artifact/old", path)
    write_dashboard_url("https://claude.ai/artifact/new", path)
    assert read_dashboard_url(path) == "https://claude.ai/artifact/new"


def test_read_strips_surrounding_whitespace(tmp_path):
    path = tmp_path / "dashboard_url.txt"
    path.write_text("  https://claude.ai/artifact/padded  \n\n")
    assert read_dashboard_url(str(path)) == "https://claude.ai/artifact/padded"


def test_read_returns_none_for_empty_file(tmp_path):
    path = tmp_path / "dashboard_url.txt"
    path.write_text("   \n")
    assert read_dashboard_url(str(path)) is None
