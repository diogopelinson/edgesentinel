# Architecture decision records

One file per architectural decision: what was decided, when, what it was
weighed against, and what it costs. A record is not edited once it is
accepted — when a decision changes, a new record supersedes the old one and
says so. The point is that a reader can see not only what the project does,
but what it considered and rejected.

| # | Decision | Date | Status |
|---|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | 2026-09-23 | Accepted |
| [0002](0002-hexagonal-architecture.md) | Hexagonal architecture, with the domain importing nothing | 2026-04-03 | Accepted |
| [0003](0003-sqlite-for-the-history.md) | SQLite, behind a queue and a writer thread, for the history | 2026-09-16 | Accepted |
| [0004](0004-cooldowns-behind-a-state-port.md) | Cooldowns behind a state port, with no clock in the engine | 2026-09-21 | Accepted |
| [0005](0005-scoring-inside-the-model-file.md) | The scoring rule lives inside the model file | 2026-09-18 | Accepted |
| [0006](0006-incidents-with-a-resolution-margin.md) | Incidents close on a margin, and the database enforces one per rule | 2026-09-22 | Accepted |
| [0007](0007-python-with-go-at-the-edges.md) | Python for the agent, Go for the fleet control plane | 2026-09-16 | Accepted |

Records 0002 to 0007 were written after the fact, from the code and the
history, when the records started. They are dated by when the decision was
taken, not by when it was written down.

## Format

Context, Decision, Consequences, and where it applies, "Revisit when" — the
condition that would make the decision worth reopening. Statuses are
*Proposed*, *Accepted*, *Superseded by NNNN* or *Deprecated*.

Prose, not bullet lists, wherever the reasoning has a shape. A decision
recorded as five fragments is a decision nobody can evaluate later.
