# 0006 — Incidents close on a margin, and the database enforces one per rule

- **Status:** Accepted
- **Date:** 2026-09-22 *(recorded retrospectively)*

## Context

A rule matching for an hour produced one alert per poll. The cooldown made that
sparser without making it meaningful: there was still nothing that said when
the episode started, nothing to acknowledge, and nothing that closed when the
machine recovered.

Grouping the firings into an episode is the obvious move. It raises three
questions that are less obvious: when does an episode end, where does its state
live, and what stops two concurrent threads from opening two episodes for the
same rule.

## Decision

**An incident groups the firings of one rule**, with states `triggered`,
`acknowledged` and `resolved`, and every event carrying its `incident_id`.
There is no `normal` state: normal is the absence of an open incident.

**It closes on a margin, not at the threshold.** The default resolution point
is the threshold minus 10% of its absolute value, away from the alarm side;
`resolve_threshold` overrides it per rule, and the loader refuses a value on
the alarm side. Without a margin, a value hovering at the threshold opens and
closes an incident on every reading — a stream of state changes describing a
situation that never changed.

**The state lives in the event database, and the engine reads it on every
evaluation** instead of holding it in memory.

**One open incident per rule is enforced by a partial unique index** —
`UNIQUE (rule_name) WHERE state != 'resolved'` — not by the engine.

Alternatives considered. **Closing at the threshold**: flapping, as above.
**A fixed absolute margin**: wrong across units — two degrees and two percent
are not the same distance. **Keeping incidents in memory with a load step at
boot**: a rebuild to write and to test, and it would not let another process
acknowledge anything. **A lock in the engine for the duplicate problem**:
correct within one process and useless the moment a second one exists.

## Consequences

Repeated firings become one episode with a beginning, an acknowledgement and an
end, and the history can still show every firing inside it.

Rereading the open incidents on every evaluation buys three things at once: the
cycle survives a restart with no loading step, another process can acknowledge
an incident while the agent runs, and there is no cached state to go stale.
The cost is one indexed query per evaluation, against a local SQLite file.

Acknowledging stops the actions and keeps the recording. The incident goes on
collecting evidence while the alerts stop repeating, and it still resolves on
its own — acknowledging says someone is on it, not that it is over.

A storage failure never silences an alert: the event is written with an empty
`incident_id`, the actions run, and the failure is logged. Four tests hold
that, including the case where the engine is blind to what is open and the
index refuses the duplicate it then tries to create.

The schema moved to version 2, migrated in place on first open.

## Revisit when

Incidents need to be visible across a fleet rather than per device. The grouping
and the closing rule stay; what changes is that a server receives them, and the
local database becomes the buffer rather than the source of truth.
