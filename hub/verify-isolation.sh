#!/bin/bash
# verify-isolation.sh — fails if hub ever touches the model.
# Run: bash hub/verify-isolation.sh   or   npm run verify (from hub/)
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "== Isolation checks =="
fail=0

# 1. No runtime import of ffanalytics (actual code, not docs/comments about vendoring)
# Only flag real import statements in .py/.js, not markdown mentions of "import ffanalytics"
if grep -R --include="*.py" --include="*.js" -E "^\s*(from|import)\s+ffanalytics" hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub imports ffanalytics (forbidden — use vendored copy or HTTP)"
  fail=1
else
  echo "✓ no ffanalytics import in hub/ (runtime code)"
fi

# 2. No DB writes (only flag executable writes like conn.execute("INSERT...), not docs)
if grep -R --include="*.py" 'conn\.execute.*INSERT INTO\|conn\.execute.*UPDATE.*SET\|cursor\.execute.*INSERT' hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub contains DB write statements"
  fail=1
else
  echo "✓ no DB writes in hub/ (runtime code)"
fi

# 3. No 0.0.0.0 binds in executable config (only vite.config.js / server.py host values, not docs)
if grep -R --include="*.js" --include="*.py" --exclude-dir=node_modules --exclude-dir=dist -E "host.*0\.0\.0\.0|\"0\.0\.0\.0\"|'0\.0\.0\.0'" hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub binds 0.0.0.0 (must be 127.0.0.1 only)"
  fail=1
else
  echo "✓ no 0.0.0.0 bind in hub/ code"
fi

# 4. hub binds are 127.0.0.1
if ! grep -q "127\.0\.0\.1" hub/vite.config.js; then echo "FAIL: vite.config.js must bind 127.0.0.1"; fail=1; else echo "✓ vite.config.js binds 127.0.0.1"; fi
if ! grep -q "127\.0\.0\.1" hub/server.py; then echo "FAIL: hub/server.py must bind 127.0.0.1"; fail=1; else echo "✓ hub/server.py binds 127.0.0.1"; fi
if ! grep -q 'mode=ro' hub/server.py; then echo "FAIL: hub/server.py must open DB with mode=ro"; fail=1; else echo "✓ hub/server.py uses mode=ro"; fi

# 5. No runtime POST to /refresh from hub (only docs may mention curl -X POST as manual step)
if grep -R --include="*.js" --include="*.py" --exclude-dir=node_modules --exclude-dir=dist -E "fetch.*POST.*refresh|axios.*refresh" hub/ 2>/dev/null | grep -v "verify-isolation" | grep -v "curl" | grep -v "never POSTs"; then
  echo "FAIL: hub tries to POST /refresh at runtime (hub must never trigger refresh)"
  fail=1
else
  echo "✓ hub never POSTs /refresh at runtime"
fi

# 6. hub has its own package.json, does not add deps to root pyproject
if grep -q "vite" hub/package.json 2>/dev/null; then echo "✓ hub owns its deps (vite in hub/package.json)"; else echo "FAIL: hub/package.json missing"; fail=1; fi
if grep -q "\"vite\"" pyproject.toml 2>/dev/null; then echo "FAIL: vite leaked into root pyproject.toml"; fail=1; else echo "✓ root pyproject.toml clean"; fi

if [ $fail -ne 0 ]; then
  echo ""
  echo "Isolation FAILED — fix above"
  exit 1
fi

echo ""
echo "All isolation checks passed ✓"
echo "Model and hub are fully separate (single repo, zero shared writes/imports)."
