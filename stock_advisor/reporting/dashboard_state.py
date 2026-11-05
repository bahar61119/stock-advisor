"""Persists the published dashboard's Artifact URL across runs.

The dashboard (`stock_advisor/reporting/dashboard_template.html`) is meant
to be a single, stable link that gets updated in place on every run, not a
fresh artifact each time (the user explicitly asked for one persistent URL
over a new link per run). Updating an existing Artifact requires passing
its `url` back to the publish call, so whichever Claude session runs the
skill needs to know the URL from the previous run -- this module is that
handoff, a plain text file outside git (instance-specific, not something
to commit or share).

`None` from `read_dashboard_url()` means "no dashboard has been published
yet" -- publish fresh and record the result with `write_dashboard_url()`.
"""
from pathlib import Path

DEFAULT_STATE_PATH = str(
    Path(__file__).resolve().parent.parent.parent / ".state" / "dashboard_url.txt"
)


def read_dashboard_url(path: str = DEFAULT_STATE_PATH) -> str | None:
    """Return the previously published dashboard's URL, or `None` if none
    has been recorded yet (first run, or the state file was removed).
    """
    try:
        content = Path(path).read_text().strip()
    except FileNotFoundError:
        return None
    return content or None


def write_dashboard_url(url: str, path: str = DEFAULT_STATE_PATH) -> None:
    """Record the dashboard's Artifact URL so the next run updates it in
    place instead of publishing a separate artifact. Creates the parent
    directory if it doesn't exist yet.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(url.strip() + "\n")
