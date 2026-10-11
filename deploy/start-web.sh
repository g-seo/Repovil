#!/bin/sh
set -eu

if [ -z "${REPOVIL_API_URL:-}" ]; then
  echo '{"level":"error","event":"deployment_environment_invalid","service":"web","missing_variables":["REPOVIL_API_URL"]}' >&2
  exit 1
fi

exec node server.js
