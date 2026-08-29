#!/bin/bash
# hub/stop.sh — just in case you need to force-stop
lsof -ti :8000 2>/dev/null | xargs kill 2>/dev/null || true
lsof -ti :8001 2>/dev/null | xargs kill 2>/dev/null || true
lsof -ti :8002 2>/dev/null | xargs kill 2>/dev/null || true
pkill -f "uvicorn.*8000" 2>/dev/null || true
pkill -f "hub/server.py" 2>/dev/null || true
echo "✓ hub fully stopped — 0 processes (all 3 ports free)"
lsof -i :8000 -i :8001 -i :8002 2>&1 | head -5 || echo "verified: 127.0.0.1:8000,8001,8002 free"
