#!/bin/bash

# 1) If running in OpenShift or with a random UID, dynamically create a passwd entry
function create_system_user_if_missing() {
  if ! whoami &> /dev/null; then
    if [[ -w /etc/passwd ]]; then
      echo "${USER_NAME:-default}:x:$(id -u):0:${USER_NAME:-default} user:${RUNWHEN_HOME}:/sbin/nologin" >> /etc/passwd
    fi
    export HOME="$RUNWHEN_HOME"
  fi
}
create_system_user_if_missing

# 2) Start metrics daemon in background
echo "Starting RunWhen metrics daemon..."
python3 "$RUNWHEN_HOME/robot-runtime/metrics_daemon.py" &
METRICS_PID=$!

# Wait a moment for metrics daemon to start
sleep 2

# Check if metrics daemon started successfully
if kill -0 $METRICS_PID 2>/dev/null; then
  echo "✅ Metrics daemon started successfully (PID: $METRICS_PID)"
else
  echo "⚠️  Metrics daemon failed to start, continuing without metrics"
fi

# 3) Set up signal forwarding to gracefully stop metrics daemon
function cleanup() {
  echo "Shutting down..."
  if kill -0 $METRICS_PID 2>/dev/null; then
    echo "Stopping metrics daemon..."
    kill -TERM $METRICS_PID 2>/dev/null
    wait $METRICS_PID 2>/dev/null
  fi
  exit 0
}
trap cleanup SIGTERM SIGINT

# 4) Start main process
# if env var WORKER_MODE_RUNNER is set then run the worker binary
# else it is older runner, run runrobot.py directly
if [ "$WORKER_MODE_RUNNER" = "true" ]; then
  echo "Starting runner worker"
  exec "$RUNWHEN_HOME/worker"
else
  echo "Executing runrobot.sh"
  "$RUNWHEN_HOME/robot-runtime/runrobot.sh"
fi
