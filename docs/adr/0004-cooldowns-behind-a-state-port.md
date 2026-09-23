# 0004 — Cooldowns behind a state port, with no clock in the engine

- **Status:** Accepted
- **Date:** 2026-09-21 *(recorded retrospectively)*

## Context

A rule's cooldown was a timestamp on the `Rule` object: the engine compared
`time.monotonic()` against `rule._last_triggered` and wrote the new value if
the rule fired. Two problems, one immediate and one structural.

The immediate one is a race. Pipelines run on an executor thread pool and share
one engine, so compare-then-write is two steps with a gap: two threads could
both read an expired cooldown and both fire the same rule.

The structural one is that multi-device deployments are in the backlog, and
cooldowns are the first state that has to be shared. `time.monotonic()` cannot
be shared: its epoch is per process, so a timestamp from one device means
nothing on another. An engine built on comparing monotonic timestamps can never
have its cooldowns made distributed, whatever is put behind it.

## Decision

Move the state behind `StatePort`, with `try_acquire(key, ttl_seconds)` as the
operation: taking the key and checking it are the same call, and it returns
whether the caller won.

The engine does not read a clock. It asks the port for
`cooldown:<rule name>`. `Rule` goes back to being only the declaration of a
rule, with no runtime state on it.

The port deliberately exposes no timestamps. Anything of the form "when did
this last fire" would leak the process-local epoch into the interface and
recreate the problem in a new shape.

`InMemoryState` is the default implementation, lock-guarded and backed by
`time.monotonic()` — monotonic rather than wall clock, because NTP can step the
wall clock backwards and freeze a cooldown. A Redis adapter will implement the
same port with `SET NX EX`, letting the server own expiry.

Alternatives considered. **A lock around the existing compare-and-write**:
fixes the race, leaves the distributed case impossible. **Passing a clock into
the engine**: testable, still per-process, and still the wrong interface.

## Consequences

The race is gone, and it is held by a test that drives twenty concurrent
callers and requires exactly one to win.

Cooldowns became distributable without the engine changing: the Redis adapter
is a new file behind an existing port.

The contract is enforced rather than described. `tests/adapters/test_state_contract.py`
is parametrised by implementation, so any new backend has to pass the same
suite, and a separate test asserts that `application/engine.py` contains no
reference to `monotonic` — the property is checkable, not merely intended.

The cost is that "when did this rule last fire" is no longer available from the
state. It is available from the history, which is where a question about the
past belongs.

## Revisit when

Some state genuinely needs a timestamp in the interface rather than a TTL — a
rate limiter over a window, for instance. That is a second operation on the
port, not a return to timestamps on the entity.
