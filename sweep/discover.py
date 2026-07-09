"""sweep.discover — daily event discovery for the shared catalog.

Harvests every event link from the FiveTool and Prospect Select public
event listings (same Playbook365 platform; fivetool_scrape already crawls
both) and queues each as a sweep_events row (idempotent). The worker then
crawls rosters overnight so every event is in every program's New-event
dropdown before anyone asks — the "crawl EVERYTHING" lane-1 from
MASS-EVENT-SWEEP.md.

Deliberately tolerant of page layout: we don't parse the listing markup,
we harvest ANY anchor whose href matches the platform's own event-URL
prefix (/public/events/<slug> on PS, /events/<slug> on FiveTool). A
listing redesign degrades to zero results + a loud log line, never junk.

PG is NOT here yet (aspx pages, unproven server-side; posture was an open
decision in the design). PG events keep flowing through the extension /
in-app Refresh until that lane is proven.

Usage: python -m sweep.discover              (all sources)
       python -m sweep.discover --url <event-url>   (lane 2: force-queue one)
"""
import argparse
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import db

UA = {"User-Agent": "RecruitingAI-sweep/1.0 (event catalog; contact: bosco.chris01@gmail.com)"}

# host -> (source tag, event-URL prefix, listing pages to harvest from)
SOURCES = {
    "fivetool.org": ("fivetool", "/events/", ["/events", "/"]),
    "play.ps-baseball.com": ("ps", "/public/events/", ["/public/events", "/"]),
}


def harvest(host, prefix, paths):
    """Return {slug: (name, url)} for every event link found on the listing pages."""
    found = {}
    pat = re.compile(re.escape(prefix) + r"([^/?#\s]+)")
    for path in paths:
        url = f"https://{host}{path}"
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  listing {url}: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            m = pat.search(a["href"])
            if not m:
                continue
            slug = m.group(1)
            ev_url = urljoin(url, a["href"].split("?")[0].split("#")[0])
            name = re.sub(r"\s+", " ", a.get_text(" ")).strip()
            if slug not in found or (name and not found[slug][0]):
                found[slug] = (name, ev_url)
        time.sleep(2.5)
    return found


def queue_url(conn, url):
    """Lane 2: a pasted event URL becomes a high-priority pending row."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    for h, (source, prefix, _) in SOURCES.items():
        if host == h and prefix in url:
            slug = url.split(prefix, 1)[1].split("/")[0].split("?")[0]
            sid = db.enqueue(conn, source, slug, "", url.split("?")[0], priority=10)
            print(f"queued {source}:{slug}" + ("" if sid else " (already known)"))
            return True
    print(f"unrecognized event URL (not FiveTool/PS): {url}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="force-queue one event URL (lane 2)")
    args = ap.parse_args()
    conn = db.connect()
    if args.url:
        sys.exit(0 if queue_url(conn, args.url) else 1)
    total_new = 0
    for host, (source, prefix, paths) in SOURCES.items():
        events = harvest(host, prefix, paths)
        new = 0
        for slug, (name, url) in events.items():
            if db.enqueue(conn, source, slug, name, url):
                new += 1
        total_new += new
        print(f"{source}: {len(events)} events on the listing, {new} new in queue")
        if not events:
            print(f"  !! zero events harvested from {host} — listing layout "
                  f"changed or blocked; check manually")
    print(f"discovery done — {total_new} new event(s) queued")


if __name__ == "__main__":
    main()
