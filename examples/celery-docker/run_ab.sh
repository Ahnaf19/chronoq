#!/usr/bin/env bash
# run_ab.sh — Run FIFO + active modes back-to-back and generate a JCT comparison plot.
#
# Usage: ./run_ab.sh
#
# Prerequisites: Docker Desktop / Colima / native Docker + Compose v2
#
# Total runtime: ~5-8 min (first run may take longer for image build).
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p artifacts

echo "======================================================================"
echo " Chronoq Docker demo — FIFO vs active JCT comparison"
echo "======================================================================"
echo ""

# ── FIFO run ──────────────────────────────────────────────────────────────
echo "[run_ab] Starting FIFO run..."
CHRONOQ_MODE=fifo docker compose up --abort-on-container-exit --build 2>&1
echo "[run_ab] FIFO run complete."
docker compose down --volumes --remove-orphans

echo ""

# ── Active run ────────────────────────────────────────────────────────────
echo "[run_ab] Starting active (LambdaRank) run..."
CHRONOQ_MODE=active docker compose up --abort-on-container-exit 2>&1
echo "[run_ab] Active run complete."
docker compose down --volumes --remove-orphans

echo ""

# ── Plot comparison ───────────────────────────────────────────────────────
echo "[run_ab] Generating JCT comparison plot..."
python plot_jct.py

echo ""
echo "[run_ab] Done. Artifacts written to ./artifacts/"
echo "         jct_comparison.png  — histogram + bar chart"
echo "         run_fifo.csv        — per-task timing (FIFO mode)"
echo "         run_active.csv      — per-task timing (active mode)"
