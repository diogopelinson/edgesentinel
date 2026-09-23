# Usage guide — edgesentinel

This guide has moved into [docs/](docs/README.md), split by what you are trying
to do. The file stays here so existing links still land somewhere useful.

The split follows [Diátaxis](https://diataxis.fr/): a page that teaches, a page
that gives you steps, a page that lists facts and a page that explains why are
four different jobs, and this file was doing all four at once.

## Where each section went

| It used to be here | It is now at |
|---|---|
| 1. CLI usage | [Run the agent](docs/how-to/run-the-agent.md) · [Command line reference](docs/reference/cli.md) |
| 2. Library usage | [Use edgesentinel as a library](docs/how-to/use-as-a-library.md) |
| 3. Connecting real cameras with MediaMTX | [Connect a real camera](docs/how-to/connect-a-camera.md) |
| 4. AI Inference Service in practice | [Run the AI Inference Service](docs/how-to/run-the-ai-service.md) |
| 5. Configuring Prometheus and Grafana | [Set up Prometheus and Grafana](docs/how-to/set-up-observability.md) · [Metrics reference](docs/reference/metrics.md) |
| 6. Creating your own sensor | [Write your own sensor](docs/how-to/write-a-sensor.md) |
| 7. Creating your own action | [Write your own action](docs/how-to/write-an-action.md) |
| 8. Interface reference | [Ports and entities](docs/reference/ports-and-entities.md) |

## What is new since

Pages that did not exist while this was one file:

- [Your first run without hardware](docs/tutorials/first-run.md) and [Watching an incident open and close](docs/tutorials/first-incident.md) — lessons, start here if you are new.
- [Configuration reference](docs/reference/configuration.md) — every field of `config.yaml`, its default, and what the loader refuses.
- [Database reference](docs/reference/database.md) — the schema of `events.db`, its indexes, migrations and retention.
- [Train an anomaly model](docs/how-to/train-an-anomaly-model.md) — and how to check it scores your sensor sensibly.
- [Explanation](docs/explanation/README.md) and [decision records](docs/adr/README.md) — why the system is shaped the way it is.

## Em português

The documentation in `docs/` is in English. The Portuguese guide is still a
single file and is still maintained: [USAGE-PTBR.md](USAGE-PTBR.md), alongside
[README-BR.md](README-BR.md).
