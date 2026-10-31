#!/bin/sh
# Container entrypoint for the single FastAPI process.
# Extra arguments replace the default command, so migration, seed, and
# maintenance jobs reuse this image without a second entrypoint.
set -eu

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8080}"
