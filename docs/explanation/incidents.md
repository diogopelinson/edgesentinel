# Incidents and hysteresis

A rule that keeps matching is one problem, not one problem per reading. This
page is about what follows from taking that sentence seriously.

## The problem with firings

Before incidents, a rule watching a CPU that sat above 80 °C for an hour
produced one alert per poll — 720 of them at a five-second interval, all
identical, none of them saying that the previous 719 were the same event.

The usual patch is a cooldown: fire, then stay quiet for N seconds. edgesentinel
has one, and it is not enough. A cooldown makes the noise sparser without
making it meaningful: there is still nothing that says "this started at 14:02",
nothing to acknowledge, and nothing that closes when the machine recovers.

## The model

An **incident** is a rule in alarm, from the first firing until the sensor
comes back. Every firing is still recorded, and each event carries the
`incident_id` of the episode it belongs to.

| State | Meaning |
|---|---|
| `triggered` | Open. Every firing still dispatches actions |
| `acknowledged` | Someone is on it. Events keep being recorded; actions stop |
| `resolved` | The sensor recovered. The next firing opens a new incident |

There is no `normal` state. Normal is the absence of an open incident —
storing it would mean one row per rule that has never fired, and a state
machine with a state that describes "nothing is happening" invites code that
asks about it.

Acknowledging is the interesting one. It does not mean the problem is over, so
the history keeps filling: the incident goes on collecting evidence while the
alerts stop repeating. An acknowledged incident still resolves on its own.

## Why closing is the hard part

Grouping firings is the easy half. An incident that never closes has to be
closed by hand, which no one does, and a month later every rule has one open
incident that means nothing.

So the incident closes itself when the reading recovers — and that is where the
naive version fails. If a rule fires above 80 and closes at 80, then a sensor
sitting at 80.0 with ordinary noise produces:

```
80.1  -> incident opened
79.9  -> incident resolved
80.2  -> incident opened
79.8  -> incident resolved
```

That is called flapping, and it is worse than no grouping at all: it is a
stream of state changes describing a situation that never changed.

The fix is **hysteresis**: open at one value, close at another, with a gap
between them. Here the default gap is 10% of the threshold's absolute value,
moved away from the alarm side — `> 80` closes at 72, `< 10` closes at 11. A
rule that needs a different distance sets `resolve_threshold` explicitly.

Ten percent is a judgement, not a law: wide enough to swallow the noise of a
cheap sensor, narrow enough that a real recovery closes the incident within a
poll or two. When it is wrong for your sensor, the config field is there, and
the loader refuses a value on the alarm side — `> 85` resolving at `90` would
close the incident with the sensor still too hot, which is precisely the bug
the margin exists to prevent.

Two operators have no numeric edge and are handled by their own rule: `==`
resolves as soon as the value changes, and `anomaly` resolves when the score
comes back below its threshold. With inference down there is no score, and no
score means no resolution — an incident stays open rather than being closed by
the absence of evidence.

## Why the state lives in the database

The engine holds no incident in memory. It reads the open incidents from the
store on every evaluation.

That sounds wasteful and buys three things, each of which would otherwise be a
feature of its own:

**Restart survival, with no loading step.** A process that crashes at 03:00 and
comes back at 03:01 continues the same incident, because "the open incidents"
is a query, not a field that needs rebuilding.

**Another process can change it.** Acknowledging happens in the database, from
the CLI or by hand, and the agent sees it on its next evaluation. No signal, no
IPC, no restart — and the second tutorial demonstrates it on a running agent.

**One open incident per rule is enforced where it can actually be enforced.**
A partial unique index — `UNIQUE (rule_name) WHERE state != 'resolved'` — makes
it a property of the storage. Two pipeline threads racing to open the same
incident produce one row and one refusal, with no lock in the application. The
refusal is logged and swallowed, like any other storage failure.

## What it does not do

An incident is context around an alert and must never be able to silence one.
If the store raises — locked database, full disk — the failure is logged, the
event is written with an empty `incident_id`, and the actions run anyway. Four
tests hold that: a failing open, a failing read of the open incidents, a
failing resolve, and an engine blinded to what is open trying to open a
duplicate.

Losing the grouping is an inconvenience. Losing the alert is the failure the
whole system exists to prevent.

## See also

- [ADR 0006](../adr/0006-incidents-with-a-resolution-margin.md) — the decision, dated, with what was rejected.
- [Watching an incident open and close](../tutorials/first-incident.md) — the same ideas, on a running agent.
- [Database reference](../reference/database.md) — the tables, the index and retention.
