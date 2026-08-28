# Runbook

## Start the API locally
`uvicorn ffanalytics.api:app --reload` (dev) or without `--reload` (daily use)

**Never** add `--host 0.0.0.0` or any tunnel/port-forward — uvicorn's default
`127.0.0.1` binding is what keeps this off the internet entirely. If you ever
want remote access (phone, etc.), that's a deliberate future decision, not a
flag to add here.

## Install the daily refresh job
1. Replace `REPLACE_WITH_ABSOLUTE_PATH` in `scripts/com.ffanalytics.refresh.plist`
   with this repo's absolute path (twice, plus the logs dir).
2. `mkdir -p logs`
3. `cp scripts/com.ffanalytics.refresh.plist ~/Library/LaunchAgents/`
4. `launchctl load ~/Library/LaunchAgents/com.ffanalytics.refresh.plist`

## Manual refresh fallback
If the laptop was asleep/closed at 7am and the launchd job didn't fire:
`curl -X POST http://localhost:8000/refresh`

## Uninstall the job
`launchctl unload ~/Library/LaunchAgents/com.ffanalytics.refresh.plist`