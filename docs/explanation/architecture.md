# Architecture

edgesentinel is built as a hexagon: ports and adapters. The claim such a
project usually makes is that it is "easy to extend". This page is about what
that means concretely here, and what it costs.

## The layers

```
core/           ports.py, entities.py, rules.py, incidents.py
                the domain. Imports nothing from the project.

application/    engine.py    evaluates rules, opens and closes incidents,
                             dispatches actions
                pipeline.py  one sensor: read -> score -> evaluate -> export
                monitor.py   the async loop and graceful shutdown

adapters/       sensors/     cpu_temp, cpu_usage, memory, camera, simulated
                inference/   dummy, onnx, tflite, remote
                actions/     log, webhook, gpio
                exporter/    Prometheus, OpenTelemetry
                store/       SQLite: events and incidents
                state/       cooldowns

config/         schema, loader (validation), mapper (config -> domain)
cli/            run, simulate, doctor, events; builder assembles everything
```

## The one rule

**Dependencies point inward.** `adapters` and `application` may import `core`;
`core` may import neither. That is the whole architecture, and it is checkable
in a second: if `core/` ever imports `sqlite3`, `requests` or `onnxruntime`,
the property is gone.

Everything else follows from it. The engine cannot know whether an incident is
stored in SQLite, Redis or a dictionary, because the only thing it can see is
`IncidentPort`. The rule evaluation cannot know whether a reading came from
`/sys/class/thermal` or from a sine wave, because all it has is a
`SensorReading`.

## What it buys, concretely

**The simulator is not a mock.** `edgesentinel simulate` runs the real engine,
the real rules, the real incident logic, the real store and the real exporter —
it swaps one adapter, the sensor. That is why a rule rehearsed in simulation
behaves the same in the field, and why this project can be developed on a
laptop without pretending.

**Tests run without hardware, network or a clock.** The suite is 380-odd tests
and none of them need a device, because every boundary is a port and every port
has a fake. The tests that do touch SQLite use a real database in a temporary
directory — a fake of your own storage engine is a fake of the part most likely
to be wrong.

**A new integration is a new file.** Telegram notifications, a Redis cooldown,
a gRPC inference backend: each is an adapter behind a port that already exists.
The core does not change, so nothing that already works can break.

**Swapping is a config line.** ONNX to TFLite, Prometheus to OTel, local
inference to a remote service. The builder reads the config and constructs a
different adapter; nothing upstream of it notices.

## The failure rule

Everything that talks to the outside world — network, disk, hardware — is
wrapped: the failure is logged and swallowed, never allowed to stop an
evaluation.

This is not defensive habit, it is a priority ordering. An edge agent exists to
report that the machine is overheating. If the history database is locked, the
webhook is timing out or the incident store is refusing writes, the alert still
has to go out. So a failing action is logged and the next action runs; a full
event queue drops the event with a warning and the alert continues; a raising
incident store produces an event with an empty `incident_id` and the alert
continues.

The one thing never swallowed is a configuration error. Those fail at startup,
loudly, because a misconfigured agent is worse than an absent one: it looks
like it is watching.

## What it costs

Indirection. Reading "what happens when a rule fires" means opening
`engine.py`, then `ports.py`, then an adapter — three files where a smaller
project would have one function. For a script that will never grow, that trade
is bad; for a system meant to gain a Redis backend, a fleet server and an OTA
updater, the cost is paid once and the benefit recurs.

There is also a discipline cost: the rule has to be *kept*. It is one careless
import from `core/rules.py` to `adapters.store.sqlite` to make the domain
depend on SQLite forever, and nothing in Python stops you. That is why it is
written in [AGENTS.md](../../AGENTS.md) and in
[CONTRIBUTING.md](../../CONTRIBUTING.md), in the same words.

## Where the language boundary sits

The agent is Python because that is where the ecosystem lock-in is: ONNX,
scikit-learn and the hardware libraries all live there. The fleet control plane
and the OTA updater are marked as Go in the roadmap, because their constraint
is deployment — a long-running network service and a binary that must run on a
device with no runtime installed.

The reasoning is in [ADR 0007](../adr/0007-python-with-go-at-the-edges.md). The
short version: a polyglot repository with a principled boundary is a strong
signal, and one with an arbitrary boundary is a weak one.
