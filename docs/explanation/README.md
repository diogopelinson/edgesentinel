# Explanation

Why the project is built the way it is. Nothing here is needed to use it —
these pages are for when something looks arbitrary and you want to know what
it was weighed against.

- **[Architecture](architecture.md)** — the hexagon, the one rule that holds it together, and what it actually buys.
- **[Incidents and hysteresis](incidents.md)** — why repeated firings become an episode, and why an incident closes somewhere other than where it opened.
- **[Scoring inside the model file](model-scoring.md)** — why normalisation and the scoring rule live in the ONNX graph instead of in the code that loads it.

For decisions as decisions — dated, with the alternatives that were rejected —
see the [decision records](../adr/README.md). These pages explain how the
system works; those record what was chosen, when, and against what.
