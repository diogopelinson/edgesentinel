# 0003 — SQLite, behind a queue and a writer thread, for the history

- **Status:** Accepted
- **Date:** 2026-09-16 *(recorded retrospectively)*

## Context

Until this decision, a rule that fired wrote a log line to stdout and that was
the end of it. Nothing could answer "what happened last night", no dashboard
could show a history, and the incident lifecycle — which needs state that
outlives the process — had nowhere to live.

The constraints are those of an edge device: it may be the only machine on
site, its network may be down precisely when something interesting happens, and
its storage is often an SD card where a single `fsync` can stall for hundreds
of milliseconds. The pipeline that would be doing the writing runs on a bounded
thread pool that also reads sensors.

## Decision

Store the history in a local SQLite file, in WAL mode, written by a dedicated
thread fed by a bounded queue.

`append()` only enqueues. The writer thread batches inserts. If the queue
fills, the event is dropped with a warning rather than blocking the caller. On
shutdown — Ctrl+C included — whatever is queued is written before the process
exits. Any storage failure is logged and swallowed.

Alternatives considered. **A JSON or CSV file**: no indexes, so every query
scans, and concurrent append plus read is a problem you end up solving badly.
**Postgres or another server**: an edge agent that needs a database server to
record its own history is an agent that stops recording when the network drops.
**Writing directly, without the queue**: simplest, and it puts an SD card's
`fsync` latency on the thread that reads sensors — the failure it prevents is
exactly the one this project cares about.

## Consequences

The history is queryable with indexes and no new dependency: SQLite is in the
standard library, so the footprint on the device does not change.

Losing an event under pressure is accepted, by design, and it is visible — the
drop is logged. The ordering is deliberate: a missing row of history is a small
loss, a delayed alert is the failure mode the system exists to prevent.

Because the store is a real embedded database, the store's own tests use a real
file in a temporary directory rather than a fake. Faking your storage engine
hides the errors it is most likely to produce.

This decision later carried the incidents as well — same file, same close(),
one thing to back up — which is [ADR 0006](0006-incidents-with-a-resolution-margin.md).

## Revisit when

A deployment needs the history of many devices queryable in one place. That is
a different component — a server that receives events — not a change of
embedded database, and the local file stays as the buffer that survives the
link being down.
