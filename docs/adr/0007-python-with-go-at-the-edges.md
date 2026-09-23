# 0007 — Python for the agent, Go for the fleet control plane

- **Status:** Accepted
- **Date:** 2026-09-16 *(recorded retrospectively)*

## Context

The backlog contains two components that are not the agent: a server that
receives heartbeats and keeps the fleet inventory, and an updater that installs
new agent versions on devices in the field. The question was whether to write
them in Python, like everything else, or to introduce a second language.

Adding a language to a project is not free — two toolchains, two test
harnesses, two sets of idioms — so the bar is that the second language must be
answering a constraint the first one cannot.

## Decision

**Python where the ecosystem is the constraint.** The agent, the AI Inference
Service and the training scripts stay Python: ONNX runtime, scikit-learn,
OpenCV, ultralytics and the GPIO libraries are there, and reimplementing that
surface in another language would be the whole project.

**Go where deployment is the constraint.** The fleet control plane and the OTA
updater are Go: a long-running network service with many idle connections, and
a binary that has to run on a device without a Python runtime — an updater that
depends on the runtime it is replacing is an updater that can brick a device
halfway through.

The boundary is recorded in `docs/roadmap.json` under
`context.language_boundary`, so it is checkable against the backlog rather than
being folklore.

Alternatives considered. **Everything in Python**: the updater would need the
runtime it may be replacing, and packaging a Python service for a device
without one means bundling an interpreter anyway. **Everything in Go**: throws
away the ML ecosystem the agent is built on. **Rust for the updater**: the same
deployment argument as Go, with a smaller ecosystem for the network service and
no second use in the backlog.

## Consequences

The repository becomes polyglot at a boundary that can be stated in one
sentence, which is the difference between a signal of judgement and a signal of
restlessness.

The two Go components must communicate with the Python agent over a wire
protocol — HTTP or gRPC with a versioned schema — rather than by sharing code.
That is a constraint worth having anyway: a device and a server that share a
data structure are a device and a server that must be deployed together.

Until those components exist, this decision costs nothing and constrains
nothing. It is recorded now so the first line of Go in the repository is the
result of a decision rather than a mood.

## Revisit when

A third component appears that fits neither rule — then the boundary needs
restating rather than stretching. Or the fleet server turns out to be small
enough that a Python service is honestly sufficient, in which case Go is left
to the updater alone, where the argument is strongest.
