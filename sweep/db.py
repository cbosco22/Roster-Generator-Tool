"""sweep.db — the sweep's only line to Postgres.

Connects with the dedicated low-privilege sweep_writer role (SWEEP_DB_URL
env; see supabase sweep-setup SQL in chat 2026-07-09 / MASS-EVENT-SWEEP.md):
it can touch public_players, sweep_events and catalog rows in events —
nothing tenant-scoped. All writes are idempotent upserts; a failed write
raises and re-queues, never blind-retries (post-event reliability lesson).
"""
import json
import os

import psycopg2
import psycopg2.extras


def connect():
    url = os.environ.get("SWEEP_DB_URL")
    if not url:
        raise SystemExit("SWEEP_DB_URL not set — add the sweep_writer pooler "
                         "connection string as a repo Actions secret.")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn


# ---------- sweep_events queue ----------

def enqueue(conn, source, source_key, name, url, priority=0, status="pending"):
    """Discovery insert — idempotent on (source, source_key)."""
    with conn.cursor() as cur:
        cur.execute(
            """insert into sweep_events (source, source_key, name, url, priority, status)
               values (%s,%s,%s,%s,%s,%s)
               on conflict (source, source_key) do nothing
               returning id""",
            (source, source_key, name, url, priority, status))
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def pop_pending(conn, sources):
    """Claim the highest-priority pending event (skip-locked so parallel
    runs never double-crawl)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """select id, source, source_key, name, url from sweep_events
               where status = 'pending' and source = any(%s)
               order by priority desc, discovered_at asc
               for update skip locked limit 1""", (list(sources),))
        row = cur.fetchone()
        if row:
            cur.execute("update sweep_events set status='crawling', attempts = attempts + 1 "
                        "where id = %s", (row["id"],))
    conn.commit()
    return row


def finish(conn, sweep_id, ok, stats=None, error=None):
    with conn.cursor() as cur:
        cur.execute(
            """update sweep_events
               set status = %s, crawled_at = now(), last_error = %s,
                   stats = coalesce(stats,'{}'::jsonb) || %s::jsonb
               where id = %s""",
            ("done" if ok else "failed", (error or "")[:800] or None,
             json.dumps(stats or {}), sweep_id))
    conn.commit()


# ---------- app catalog (events table) ----------

def upsert_catalog_event(conn, name, roster_json, schedule_url, location=""):
    """One catalog row per event name: insert, or refresh the roster on an
    existing catalog row (T-24h re-crawl semantics)."""
    with conn.cursor() as cur:
        cur.execute("select id from events where is_catalog = true and name = %s limit 1", (name,))
        row = cur.fetchone()
        if row:
            cur.execute("update events set roster = %s, schedule_url = %s where id = %s",
                        (roster_json, schedule_url or "", row[0]))
        else:
            cur.execute(
                """insert into events (name, csv, roster, schedule_url, location, is_catalog)
                   values (%s, '', %s, %s, %s, true)""",
                (name, roster_json, schedule_url or "", location or ""))
    conn.commit()


# ---------- shared pool ----------

def upsert_pool(conn, recs):
    """Fill-if-empty upsert into public_players (never clobber a value the
    pool already has — richer sources like the PBR crawler own overwrites)."""
    if not recs:
        return 0
    rows = [(r["identity_hash"], r["name"], r.get("grad_year"), r.get("state"),
             r.get("position"), r.get("commit"), json.dumps(r.get("sources", {})))
            for r in recs]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            insert into public_players (identity_hash, name, grad_year, state,
                                        position, commit, sources)
            values %s
            on conflict (identity_hash) do update set
              position = coalesce(nullif(public_players.position,''), excluded.position),
              commit   = coalesce(nullif(public_players.commit,''),   excluded.commit),
              sources  = public_players.sources || excluded.sources,
              updated_at = now()
        """, rows)
    conn.commit()
    return len(rows)
