#!/bin/bash

# Generate a unique identifier for this execution using session and runrequest IDs
# Structure: RW_SESSION_ID/RW_RUNREQUEST_ID
SESSION_ID=""
RUNREQUEST_ID=""

if [ -n "$RW_SESSION_ID" ]; then
    SESSION_ID="$RW_SESSION_ID"
else
    # Generate a session-like ID if not available
    SESSION_ID="session-$(date +%s)"
fi

if [ -n "$RW_RUNREQUEST_ID" ]; then
    RUNREQUEST_ID="$RW_RUNREQUEST_ID"
else
    # Generate a runrequest-like ID if not available
    RUNREQUEST_ID="runreq-$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$(date +%s)-$$")"
fi

# Create hierarchical execution-specific temporary directory
EXECUTION_TMPDIR="$TMPDIR/executions/$SESSION_ID/$RUNREQUEST_ID"
CODEBUNDLE_DIR="$EXECUTION_TMPDIR/codebundle"
LOGS_DIR="$EXECUTION_TMPDIR/robot_logs"

# Export the execution-specific paths
export RW_EXECUTION_TMPDIR="$EXECUTION_TMPDIR"
export RW_EXECUTION_LOGS_DIR="$LOGS_DIR"

echo "$(date) Using hierarchical execution directories:"
echo "$(date) Session ID: $SESSION_ID"
echo "$(date) Runrequest ID: $RUNREQUEST_ID"
echo "$(date) Execution directory: $EXECUTION_TMPDIR"
echo "$(date) Codebundle directory: $CODEBUNDLE_DIR"
echo "$(date) Logs directory: $LOGS_DIR"

# Check and log debug mode status
if [ "$RW_DEBUG_KEEP_ARTIFACTS" = "true" ]; then
    echo "$(date) 🐛 DEBUG MODE ENABLED: Artifacts will be preserved after execution"
    echo "$(date) 🐛 DEBUG MODE: Set RW_DEBUG_KEEP_ARTIFACTS=false or unset to enable cleanup"
else
    echo "$(date) 🧹 CLEANUP MODE: Artifacts will be cleaned up after execution"
    echo "$(date) 🧹 CLEANUP MODE: Set RW_DEBUG_KEEP_ARTIFACTS=true to preserve for debugging"
fi

# Cleanup function
cleanup() {
    # Check if debug mode is enabled to keep artifacts
    if [ "$RW_DEBUG_KEEP_ARTIFACTS" = "true" ]; then
        echo "$(date) DEBUG MODE: Keeping execution directories for Session: $SESSION_ID, Runrequest: $RUNREQUEST_ID"
        echo "$(date) DEBUG MODE: Artifacts preserved at: $EXECUTION_TMPDIR"
        echo "$(date) DEBUG MODE: To manually cleanup later, run: rm -rf $EXECUTION_TMPDIR"
        return
    fi
    
    echo "$(date) Cleaning up execution-specific directories for Session: $SESSION_ID, Runrequest: $RUNREQUEST_ID"
    rm -rf "$EXECUTION_TMPDIR"
    echo "$(date) Cleanup completed for Session: $SESSION_ID, Runrequest: $RUNREQUEST_ID"
    
    # Also clean up empty parent session directory if it exists and is empty
    SESSION_DIR="$TMPDIR/executions/$SESSION_ID"
    if [ -d "$SESSION_DIR" ] && [ -z "$(ls -A "$SESSION_DIR" 2>/dev/null)" ]; then
        echo "$(date) Removing empty session directory: $SESSION_DIR"
        rmdir "$SESSION_DIR" 2>/dev/null || true
    fi

    if [ "$RW_DEBUG_KEEP_ARTIFACTS" != "true" ]; then
        echo "$(date) 🔪 Killing stray processes in PGID $$"
        # Negative PID ==> whole process group
        kill -TERM -$$ 2>/dev/null || true
        sleep 2
        kill -KILL -$$ 2>/dev/null || true
    fi
    echo "After cleanup pids.current = $(cat /sys/fs/cgroup/$(awk -F: '/pids/ {print $3}' /proc/$$/cgroup)/pids.current)"
}

# Set up cleanup trap for script exit
trap cleanup EXIT

# 1) Expand the RW_PATH_TO_ROBOT environment variable if it contains placeholders
expanded_robot_path="$RW_PATH_TO_ROBOT"
if [[ "$expanded_robot_path" == *'$(RUNWHEN_HOME)'* ]]; then
  expanded_robot_path="${expanded_robot_path//\$(RUNWHEN_HOME)/$RUNWHEN_HOME}"
fi
if [[ "$expanded_robot_path" == *'$(HOME)'* ]]; then
  expanded_robot_path="${expanded_robot_path//\$(HOME)/$HOME}"
fi

# 2) Export path to immutable copy of robot
export RW_PATH_TO_ROBOT_IMMUTABLE="$expanded_robot_path"

# 3) Extract the directory portion (base directory) and the filename from the RW_PATH_TO_ROBOT_IMMUTABLE
robot_dir="$(dirname "$RW_PATH_TO_ROBOT_IMMUTABLE")"
robot_file="$(basename "$RW_PATH_TO_ROBOT_IMMUTABLE")"

# 4) Create execution-specific directories
mkdir -p "$CODEBUNDLE_DIR"
mkdir -p "$LOGS_DIR"

# 5) Make the directories writable
chmod 1777 "$EXECUTION_TMPDIR"

# 6) Copy the contents of the immutable directory to the execution-specific directory
cp -r "$robot_dir/." "$CODEBUNDLE_DIR" 2>/dev/null || {
  echo "Warning: Could not copy from '$robot_dir' to '$CODEBUNDLE_DIR'."
}

# 7) Export RW_PATH_TO_ROBOT to point to the execution-specific directory
export RW_PATH_TO_ROBOT="$CODEBUNDLE_DIR/$robot_file"

# 8) Move into that directory so Robot's CURDIR references it
cd "$CODEBUNDLE_DIR" || exit 1

# 9) Log robot script to be executed
echo "`date` Executing ----------------------------- $RW_PATH_TO_ROBOT -----------------------------"
echo "WORKER_POOL"    : "${WORKER_POOL:-}"
echo "WORKER_ID"      : "${WORKER_ID:-}"
echo "WORKER_STARTTS" : "${WORKER_STARTTS:-}"


# 10) Run the robot with execution-specific logs directory
exec setsid python "$RUNWHEN_HOME/robot-runtime/runrobot.py" --logs "$LOGS_DIR"

# 11) Log robot script just executed
echo "`date` Executed ------------------------------ $RW_PATH_TO_ROBOT -----------------------------"

# Note: cleanup() will be called automatically on script exit due to the trap
