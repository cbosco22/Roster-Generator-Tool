# Data Privacy & Confidentiality — draft agreement + engineering notes

_Draft 2026-07-05. Plain-English first; a real attorney turns this into the
signed version before tenant #2 onboards. The engineering commitments are
buildable and mostly built — nothing here is marketing fiction._

## The situation we're honest about

The operator of this platform (Navy Baseball's recruiting coordinator) is a
**direct competitor** of every program that uses it. That conflict doesn't
get hand-waved; it gets engineered around, audited, and signed.

## What each program is promised

1. **Your board is yours.** Player lists, ratings, notes, depth charts,
   travel-program tiers, and event tags belong to your program. We claim no
   rights to them, ever.
2. **No program can see another program's data. Period.** Enforced by
   database row-level security — not by application code, not by policy,
   by the database itself. Before any second program joined, an
   adversarial test suite attempted cross-tenant reads and had to fail
   100% of them.
3. **The operator does not look.** Nobody on the platform side — including
   the operator personally — views your player names, ratings, or notes in
   the course of running the service:
   - Automated cross-tenant tooling (enrichment, duplicate detection) joins
     on **one-way hashes**, not names.
   - All privileged (service-role) access is **logged to an audit table
     your admin can read**. You can verify nobody looked, any day.
   - Support access to your data happens only in a **time-boxed session
     your admin grants** by clicking a button, and it's in the audit log.
4. **What we don't claim:** true zero-knowledge encryption. Server features
   you rely on (PDF book generation, public-data enrichment, AI note
   filing) must process names to work. The promise is engineered blindness
   plus auditability plus this contract — not cryptographic impossibility.
   We say this out loud because trust built on an overclaim dies at the
   first technical question.
5. **The shared public-data pool contains only public facts** (measurables,
   rankings, commitments, harvested academics) sourced from public pages.
   Your evaluations never enter it. Your board benefits from it; it learns
   nothing from your board except that a public identity was requested —
   by hash, not by name.
6. **Leave whole.** Export everything (spreadsheet + PDFs) any time,
   one tap. Delete your program and all its rows are gone (real deletion,
   cascade, not a soft-delete we keep).
7. **Minors' data care:** boards contain high-schoolers' info. No
   link-shared documents, no public endpoints — authenticated access only,
   per-device sessions, and the export files carry the same duty of care
   on the program's side.

## Draft disclaimer language (for the signature page)

> The Platform is operated by an individual who also engages in collegiate
> recruiting. The Platform is engineered so that no program's recruiting
> data (player identities, evaluations, rankings, notes, or organizational
> preferences) is visible to any other program or to the operator in the
> normal course of operation. Privileged administrative access is
> technically restricted, logged, and reviewable by your program's
> administrator. The operator agrees not to access, view, use, or derive
> competitive benefit from any program's recruiting data, and any support
> access occurs only with your administrator's explicit, time-limited,
> logged authorization. Violation of this section is grounds for immediate
> termination, deletion of the operator's access rights, and [remedies —
> attorney to draft].

## Engineering checklist backing the promises

- [ ] RLS policies on every tenant table (`platform_schema.sql`) ✍ drafted
- [ ] Adversarial RLS test suite (login as A, attempt all reads/writes on B;
      CI-gated so a schema change can't silently open a hole)
- [ ] `access_audit` table + admin-readable policy ✍ drafted
- [ ] Hash-join enrichment path (no plaintext names in cross-tenant jobs)
- [ ] Support-session grant flow (button → temporary role → auto-expiry)
- [ ] One-tap full export (xlsx + PDFs)
- [ ] Cascade delete verified end to end
- [ ] Attorney pass over this document
