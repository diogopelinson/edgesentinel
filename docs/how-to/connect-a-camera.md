# Connect a real camera

Publishing an RTSP camera through MediaMTX and consuming it from the agent.

## Why MediaMTX exists

Cheap IP cameras accept only **1-2 simultaneous RTSP connections**. Without MediaMTX, if edgesentinel is connected, VLC can't open the stream. With MediaMTX:

```
Camera ──▶ MediaMTX ──▶ edgesentinel (YOLO)
                   ├──▶ VLC / browser
                   ├──▶ Smart Incident Management
                   └──▶ disk recording
```

The camera makes one connection. MediaMTX distributes to as many consumers as needed.

## Step 1 — Start MediaMTX

```bash
cd infra/docker
docker compose up -d mediamtx
docker compose ps
# mediamtx   Up   :8554 (RTSP), :8888 (HLS), :8889 (WebRTC)
```

## Step 2 — Camera publishes to MediaMTX

**Option A — Camera supports native RTSP push**

In the camera's web interface, set the stream destination to:
```
rtsp://YOUR_PC_IP:8554/camera_01
```

**Option B — Relay with FFmpeg**

```bash
# Ubuntu/Raspberry Pi: sudo apt install ffmpeg
ffmpeg -i rtsp://admin:password@192.168.1.100:554/stream \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

**Option C — Simulate with a local video**

```bash
ffmpeg -re -i test_video.mp4 \
       -c copy \
       -f rtsp rtsp://localhost:8554/camera_01
```

## Step 3 — Verify the stream

Open in VLC: `rtsp://localhost:8554/camera_01`

Or via browser (HLS): `http://localhost:8888/camera_01/index.m3u8`

## Step 4 — edgesentinel consumes from MediaMTX

```yaml
cameras:
  - sensor_id: camera_01
    source: "rtsp://localhost:8554/camera_01"   # MediaMTX, not the camera directly
    name: "Entrance Camera"
    fps_limit: 1.0     # 1fps is enough for detection — doesn't overload hardware
    simulated: false
```

## Step 5 — Multiple cameras

```yaml
cameras:
  - sensor_id: camera_entrance
    source: "rtsp://localhost:8554/camera_entrance"
    fps_limit: 1.0
    simulated: false

  - sensor_id: camera_storage
    source: "rtsp://localhost:8554/camera_storage"
    fps_limit: 0.5    # 1 frame every 2 seconds — low-risk area
    simulated: false
```

---
