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
# Scoped to .py SQL patterns (DELETE FROM / DROP TABLE / CREATE TABLE / .commit()
# live here — .js Map.delete() and CSS drop-shadow are NOT SQL and are excluded
# by scoping this gate to --include="*.py").
if grep -R --include="*.py" 'conn\.execute.*INSERT INTO\|conn\.execute.*UPDATE.*SET\|cursor\.execute.*INSERT' hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub contains DB write statements"
  fail=1
elif grep -R --include="*.py" --exclude="verify-isolation.sh" -E "DELETE\s+FROM|DROP\s+TABLE|CREATE\s+TABLE|\.commit\s*\(" hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub contains destructive SQL or commit (DELETE/DROP/CREATE/commit forbidden — read-only)"
  fail=1
else
  echo "✓ no DB writes in hub/ (runtime code)"
fi

# 2b. No write-mode open() in hub Python (read-only proxy must never open DB
# or files for writing). Flags open(path, "w"/"a"/"w+"/"wb") — single-arg
# open(path) reads are fine. Excludes urlopen (urllib) which is read-only HTTP.
if grep -R --include="*.py" --exclude-dir=__pycache__ -E "[^l]open\s*\([^)]*,\s*[\"'].*[wa]" hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub opens files for writing (open with w/a mode forbidden — read-only)"
  fail=1
else
  echo "✓ no write-mode open() in hub/ (runtime code)"
fi

# 2c. Every hub Python file using sqlite3.connect must also use mode=ro.
# hub/server.py connects via file:...?mode=ro URI, so it passes; a future
# read-write connect without mode=ro fails this gate.
SQLITE_VIOLATION=0
for f in $(grep -R --include="*.py" --exclude-dir=__pycache__ -l "sqlite3\.connect" hub/ 2>/dev/null); do
  case "$f" in
    *verify-isolation*) continue ;;
  esac
  if ! grep -q "mode=ro" "$f"; then
    echo "FAIL: $f uses sqlite3.connect without mode=ro (must be read-only)"
    SQLITE_VIOLATION=1
    fail=1
  fi
done
if [ "$SQLITE_VIOLATION" = "0" ]; then
  echo "✓ hub sqlite3.connect is mode=ro only"
fi

# 3. No 0.0.0.0 binds in executable config (only vite.config.js / server.py host values, not docs)
if grep -R --include="*.js" --include="*.py" --exclude-dir=node_modules --exclude-dir=dist -E "host.*0\.0\.0\.0|\"0\.0\.0\.0\"|'0\.0\.0\.0'" hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub binds 0.0.0.0 (must be 127.0.0.1 only)"
  fail=1
elif grep -R --include="*.sh" --include="*.py" --include="*.js" --exclude-dir=node_modules --exclude-dir=dist -E "\-\-host[^|&;]*0\.0\.0\.0" hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub passes --host 0.0.0.0 (must be 127.0.0.1 only)"
  fail=1
else
  echo "✓ no 0.0.0.0 bind in hub/ code"
fi

# 4. hub binds are 127.0.0.1
if ! grep -q "127\.0\.0\.1" hub/vite.config.js; then echo "FAIL: vite.config.js must bind 127.0.0.1"; fail=1; else echo "✓ vite.config.js binds 127.0.0.1"; fi
if ! grep -q "127\.0\.0\.1" hub/server.py; then echo "FAIL: hub/server.py must bind 127.0.0.1"; fail=1; else echo "✓ hub/server.py binds 127.0.0.1"; fi
if ! grep -q 'mode=ro' hub/server.py; then echo "FAIL: hub/server.py must open DB with mode=ro"; fail=1; else echo "✓ hub/server.py uses mode=ro"; fi

# 5. No runtime POST to /refresh from hub (only docs may mention curl -X POST as manual step)
# hub/start.sh (.sh launcher) is explicitly allowed to POST /refresh — this gate
# covers runtime .js/.py only. Flags fetch/axios POST refresh AND curl POST refresh.
if grep -R --include="*.js" --include="*.py" --exclude-dir=node_modules --exclude-dir=dist -E "fetch.*POST.*refresh|axios.*refresh" hub/ 2>/dev/null | grep -v "verify-isolation" | grep -v "curl" | grep -v "never POSTs"; then
  echo "FAIL: hub tries to POST /refresh at runtime (hub must never trigger refresh)"
  fail=1
elif grep -R --include="*.js" --include="*.py" --exclude-dir=node_modules --exclude-dir=dist -E "curl[^|&;]*POST[^|&;]*refresh" hub/ 2>/dev/null | grep -v "verify-isolation"; then
  echo "FAIL: hub runtime code curl-POSTs /refresh (only hub/start.sh launcher and docs may)"
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
