# Chronoq Docker Compose Celery Demo

A full-broker demo stack showing wall-clock Job Completion Time (JCT) reduction when
switching from FIFO to Chronoq's LambdaRank active scheduling on a real Celery + Redis
setup. This is the artifact that anchors the v0.2.0 launch.

## What this demonstrates

- **Real broker**: Redis 7 as the Celery message broker and result backend.
- **Real workers**: Celery worker with `--concurrency=4` processing 500 heterogeneous jobs.
- **Wall-clock JCT**: measured from `apply_async` submission to `result.ready()`.
- **Mode comparison**: run FIFO (`CHRONOQ_MODE=fifo`) then active (`CHRONOQ_MODE=active`) back-to-back
  using the same 500-job workload (fixed seed), then diff the JCT distributions.

### Task types (synthetic profile)

| Task type | Mean duration | Description |
|-----------|--------------|-------------|
| `resize`    | ~20 ms  | Small image resize proxy |
| `analyze`   | ~90 ms  | Feature extraction proxy |
| `compress`  | ~150 ms | File compression proxy   |
| `encode`    | ~400 ms | Audio/video encode proxy |
| `transcode` | ~1800 ms| Heavy transcode proxy    |

The workload is a random mixture of all five types so the ranker has a clear signal to
exploit: scheduling short tasks first reduces mean JCT.

## Prerequisites

- **Docker Desktop** (macOS/Windows) or **Colima** or native **Docker Engine** (Linux).
- **Compose v2** (`docker compose` — not `docker-compose`). Included with Docker Desktop.
- **Python 3.11+** in your local environment for running `plot_jct.py`.
- `matplotlib` and `numpy` available locally (installed by `uv sync` in the monorepo root).
- ~2 GB disk space for the Docker image build.

### macOS with Docker Desktop

```bash
# Install Docker Desktop from https://www.docker.com/products/docker-desktop/
# or via Homebrew:
brew install --cask docker
open -a Docker   # start the daemon
```

### macOS with Colima

```bash
brew install colima docker docker-compose
colima start --cpu 4 --memory 4
```

## How to run

From the monorepo root, install local deps (needed for `plot_jct.py`):

```bash
uv sync
```

Then:

```bash
cd examples/celery-docker
./run_ab.sh
```

The script:

1. Builds the Docker image (first run only — cached on subsequent runs).
2. Starts Redis + worker + producer in `CHRONOQ_MODE=fifo`.
3. Waits for all 500 jobs to complete, writes `artifacts/run_fifo.csv`.
4. Tears down and repeats in `CHRONOQ_MODE=active`.
5. Writes `artifacts/run_active.csv`.
6. Calls `python plot_jct.py` to produce `artifacts/jct_comparison.png`.

Expected total runtime: **5–8 minutes** on an 8-core laptop (first build may add 3–5 min).

## Expected output

```
JCT comparison  (wall-clock, 500 jobs, 4 workers)
Mode         mean_jct      p99_jct
--------------------------------------
FIFO          1 230 ms      6 100 ms
Active          920 ms      4 500 ms

Mean JCT improvement: +25.2%  (gate: ≥15%)
P99  JCT improvement: +26.2%

GATE PASS: mean JCT improvement 25.2% >= 15%.
```

The exact numbers vary by machine speed; the signal (active < FIFO) is deterministic
given the fixed seed.

### Generated plot (`artifacts/jct_comparison.png`)

The PNG contains two panels:

- **Left**: overlaid semi-transparent histograms — FIFO (orange) vs Chronoq active (blue).
  Active mode shifts the distribution left (shorter jobs complete sooner).
- **Right**: mean and p99 bar chart with percentage improvement annotations.

## Recording a 30-second demo video

The two runs and final plot are designed to fit in a single terminal session.

### macOS — built-in screen recording

1. Open **QuickTime Player** → File → New Screen Recording.
2. Click the record button, then select the terminal window.
3. Run `./run_ab.sh` in a second terminal tab.
4. Open `artifacts/jct_comparison.png` in Preview as the final frame.
5. Stop recording; export as MP4.

### macOS — ffmpeg + screencapture

```bash
# Start recording in background (macOS 10.15+)
screencapture -V 30 demo_recording.mov &

# Run the demo
./run_ab.sh

# Open the plot
open artifacts/jct_comparison.png

# The screencapture process stops automatically after 30 seconds.
```

### Linux — ffmpeg

```bash
# Record the terminal window (replace :0 with your display)
ffmpeg -video_size 1280x720 -framerate 25 -f x11grab -i :0.0+0,0 \
    -t 90 demo_recording.mp4 &

./run_ab.sh
open artifacts/jct_comparison.png   # or: xdg-open artifacts/jct_comparison.png
```

## Running individual modes manually

```bash
# FIFO only
CHRONOQ_MODE=fifo docker compose up --abort-on-container-exit --build
docker compose down

# Active only
CHRONOQ_MODE=active docker compose up --abort-on-container-exit
docker compose down
```

## Caveats

- **Image size**: ~1 GB uncompressed (python:3.11-slim + LightGBM + Celery + numpy).
- **Worker timing**: durations are `time.sleep`-based (synthetic). Real workloads will
  show similar or larger JCT gaps because LambdaRank benefits grow with variance.
- **Platform note**: tested on macOS 14 (Apple Silicon) with Docker Desktop 4.29 and
  macOS 14 (Intel) with Colima 0.6. Should work on Linux with Docker Engine 24+.
- **`CHRONOQ_MODE=shadow`**: also supported — tasks are scored and logged but dispatched
  in FIFO order. Useful for validation without changing scheduling behaviour.
