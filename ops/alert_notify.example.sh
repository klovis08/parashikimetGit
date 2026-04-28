#!/usr/bin/env bash
# Example REGISTRY_PIPELINE_ALERT_CMD: read JSON from stdin; extend for email, Slack, etc.
set -euo pipefail
payload="$(cat)"
echo "$(date -Is) alert: $payload" >>/var/log/parashikimet/alert_hook.log
exit 0
