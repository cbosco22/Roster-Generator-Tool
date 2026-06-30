"""
Pull the live Navy Recruiting Sheet 2.0 as xlsx via a Google service account.

Sheet 2.0 is owned by Chris (cloned from the old USNA-owned sheet so it can
finally be read programmatically). Treating it as the source of truth means
coaches never have to manually export/upload an xlsx, and Chris never has to
git-commit a fresh export to GitHub after a board update — the app re-pulls
on container boot / cache expiry instead.
"""
import requests
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request

RECRUITING_SHEET_ID = "15XDpXkOLtGqyZaEVq3OvbugnB2e1XPbEzWJowPJCVfs"
_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_EXPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def fetch_recruiting_xlsx(service_account_info: dict, dest_path: str,
                           sheet_id: str = RECRUITING_SHEET_ID) -> None:
    """Download `sheet_id` as xlsx using a service-account credential and
    write it to `dest_path`. Raises on any failure — caller decides how to
    surface that (Admin tab shows it, startup sync swallows it and falls
    back to whatever xlsx is already on disk)."""
    creds = Credentials.from_service_account_info(service_account_info, scopes=_SCOPES)
    creds.refresh(Request())
    url = f"https://www.googleapis.com/drive/v3/files/{sheet_id}/export"
    resp = requests.get(url, params={"mimeType": _EXPORT_MIME},
                         headers={"Authorization": f"Bearer {creds.token}"},
                         timeout=30)
    resp.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(resp.content)
