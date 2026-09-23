# 0002 — Hexagonal architecture, with the domain importing nothing

- **Status:** Accepted
- **Date:** 2026-04-03 *(recorded retrospectively)*

## Context

The agent has to read hardware sensors, run an ML model, evaluate rules, drive
GPIO, export metrics and store history. Each of those is a different library
with a different failure mode, and most of them cannot run on the machine the
code is written on: development happens on Windows, deployment on a Raspberry
Pi with sensors, a camera and a relay.

A straightforward layered design — a sensors module, a rules module, a
metrics module, each importing the libraries it needs — would have meant that
evaluating a rule required `onnxruntime` importable, that a test for a
threshold needed a thermal file to exist, and that trying Datadog instead of
Prometheus meant editing the rule engine.

## Decision

Ports and adapters, with one rule: **dependencies point inward.**

`core/` holds the domain — the port interfaces, the immutable entities, the
rules and the incidents — and imports nothing from the rest of the project and
nothing third-party. `adapters/` implements the ports against real
infrastructure. `application/` wires them together and owns the flow.

A new integration is a new adapter behind an existing port. If it needs a new
port, the port is defined in `core/ports.py` and the domain stays unaware of
what implements it.

Alternatives considered: a plain layered architecture, rejected because the
dependency direction it implies puts infrastructure inside the rule engine; and
a plugin system with entry points, rejected as machinery for an extensibility
nobody had asked for — adapters in a directory are the same thing without the
indirection.

## Consequences

The simulator is not a mock. `edgesentinel simulate` runs the real engine, the
real rules, the real store and the real exporter with one adapter swapped, so
what is rehearsed on a laptop is what runs on the device.

The test suite needs no hardware, no network and no clock, because every
boundary is a port and every port has a fake. That is why the project can have
hundreds of tests while the target hardware sits in a drawer.

The cost is indirection: following "what happens when a rule fires" means
`engine.py`, then `ports.py`, then an adapter. For a script that would never
grow, that is a bad trade. For a system with a Redis backend, a fleet server
and an OTA updater in its backlog, it is paid once.

The rule also has to be kept by hand. One careless import in `core/` and the
domain depends on SQLite forever, with nothing in Python objecting — hence the
same sentence in [AGENTS.md](../../AGENTS.md) and
[CONTRIBUTING.md](../../CONTRIBUTING.md).

## Revisit when

`core/` needs a third-party import that cannot be pushed into an adapter, or
the port count grows to the point where the indirection costs more than the
substitutability buys.
