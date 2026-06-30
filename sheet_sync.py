"""
Pull the live Navy Recruiting Sheet 2.0 as xlsx.

Sheet 2.0 is owned by Chris and shared as "anyone with the link can view"
(confirmed intentional with Chris 2026-06-30 - the sheet has sensitive
player data, including minors' info, so this isn't a decision to revisit
without checking with him first). That sharing setting means Drive's
export endpoint works with a plain unauthenticated request - no GCP
project or service account needed.

We tried a service-account key first; Chris's GCP org has
iam.disableServiceAccountKeyCreation enforced (a Google "Secure by
Default" policy), which blocked it. This simpler approach sidesteps that
entirely.

This only covers READ access. If a future feature needs to write back to
the sheet (e.g. post-event auto-rating - see CLAUDE.md backlog), that
needs real authentication again - either someone with the Organization
Policy Administrator role grants a project-level exception to create a
service-account key, or an OAuth flow is built instead. Link-sharing
alone can't write.
"""
import requests

RECRUITING_SHEET_ID = "15XDpXkOLtGqyZaEVq3OvbugnB2e1XPbEzWJowPJCVfs"


def fetch_recruiting_xlsx(dest_path: str, sheet_id: str = RECRUITING_SHEET_ID) -> None:
    """Download `sheet_id` as xlsx via Drive's public export endpoint and
    write it to `dest_path`. Raises on any failure (including the sheet
    ever losing its link-sharing setting) - caller decides how to surface
    that (Admin tab shows it, startup sync swallows it and falls back to
    whatever xlsx is already on disk)."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
