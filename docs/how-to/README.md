# How-to guides

Steps for a goal you already have. Unlike the [tutorials](../tutorials/README.md),
these assume you know what you want and skip the explanations — when you want
the reasoning, it is in [Explanation](../explanation/README.md), and the exact
values are in [Reference](../reference/README.md).

## Running it

- **[Run the agent](run-the-agent.md)** — with real hardware and without it, and how to read the history it records.
- **[Use edgesentinel as a library](use-as-a-library.md)** — embedding the pieces in your own Python process instead of running the CLI.

## Extending it

- **[Write your own sensor](write-a-sensor.md)** — implementing `SensorPort` for a device the project does not ship, including the availability contract.
- **[Write your own action](write-an-action.md)** — making a firing rule do something the project does not ship.

## Cameras and inference

- **[Connect a real camera](connect-a-camera.md)** — publishing an RTSP camera through MediaMTX and consuming it from the agent.
- **[Run the AI Inference Service](run-the-ai-service.md)** — the containerised service that holds YOLO and the ONNX models, and how to add a model to it.
- **[Train an anomaly model](train-an-anomaly-model.md)** — producing `anomaly.onnx` and checking that it scores your sensor sensibly.

## Observability

- **[Set up Prometheus and Grafana](set-up-observability.md)** — both collection modes, importing the dashboard, and the queries worth having.
