# 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

The project's design decisions were documented in the README as a list of
short paragraphs — hexagonal architecture, direct `/proc` reading, cooldowns
behind a port, scoring inside the model file. The list is good at saying what
the project does. It is bad at three things a reader eventually needs:

- **When.** A decision taken in April under different constraints reads
  identically to one taken last week.
- **Against what.** The README says `/proc` is read directly. It does not say
  that `psutil` was the alternative, or why it lost.
- **Whether it still holds.** Nothing in a README paragraph tells you what
  would make it wrong.

The third is the expensive one. Without it, every decision is either treated as
permanent or relitigated from scratch.

## Decision

Keep architecture decision records in `docs/adr/`, numbered sequentially, one
file per decision, in the format described in that directory's README.

A record is immutable once accepted. Changing a decision means writing a new
record that supersedes the old one; the old file stays, with its status
updated. The history of the thinking is the artifact — a decision log that
gets edited to match current opinion is just documentation with extra steps.

Each record carries a *Revisit when* line: the condition under which it should
be reopened. A decision with no such condition is either trivial or
under-examined.

The existing decisions in the README are recorded retrospectively, dated by
when they were taken, with that fact stated in the index. The README keeps its
short summaries and links here.

## Consequences

A design discussion now has a place to land, and an argument settled twice is
visible as such.

The cost is a small ritual: a change that alters the shape of the system needs
a file, not just a commit. That is the intent — the friction is proportional to
how much the decision constrains future work.

There is also a failure mode to watch: records written to look thorough rather
than to be read. The defence is that every record must name the alternatives
that were actually considered. A record with no rejected option is a record
that skipped the thinking.

## Revisit when

The number of records makes the index hard to scan — past thirty or so — and
grouping by area becomes worth more than a flat list.
