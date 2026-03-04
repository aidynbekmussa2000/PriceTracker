#!/bin/bash

# Ralph Wiggum loop for price_tracker market expansion.
# Runs one fresh agent invocation per iteration.

set -u

if [ -z "${1:-}" ]; then
  echo "Usage: $0 <iterations>"
  echo "Example: $0 20"
  exit 1
fi

MAX_ITERATIONS="$1"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROMPT_FILE="$ROOT_DIR/ralph/PROMPT.md"
PLAN_FILE="$ROOT_DIR/ralph/plan.md"
OUTPUT_FILE="/tmp/ralph_output.txt"

# Agent command can be overridden, default is Claude CLI.
AGENT_BIN="${AGENT_BIN:-claude}"
AGENT_MODE="${AGENT_MODE:-text}"

if [ ! -f "$PROMPT_FILE" ]; then
  echo "Error: PROMPT.md not found at $PROMPT_FILE"
  exit 1
fi

if [ ! -f "$PLAN_FILE" ]; then
  echo "Error: plan.md not found at $PLAN_FILE"
  exit 1
fi

run_agent() {
  if [ "$AGENT_MODE" = "stream-json" ]; then
    "$AGENT_BIN" -p "$(cat "$PROMPT_FILE")" \
      --dangerously-skip-permissions \
      --output-format stream-json 2>&1 | tee "$OUTPUT_FILE" || true
  else
    "$AGENT_BIN" -p "$(cat "$PROMPT_FILE")" \
      --dangerously-skip-permissions \
      --output-format text 2>&1 | tee "$OUTPUT_FILE" || true
  fi
}

echo "========================================"
echo "  Ralph Wiggum Loop"
echo "  Project: price_tracker"
echo "========================================"
echo "Max Iterations: $MAX_ITERATIONS"
echo "Agent: $AGENT_BIN (mode=$AGENT_MODE)"
echo "Prompt: $PROMPT_FILE"
echo "Plan: $PLAN_FILE"
echo "Working Directory: $ROOT_DIR"
echo "========================================"
echo ""

cd "$ROOT_DIR" || exit 1

for ((i=1; i<=MAX_ITERATIONS; i++)); do
  echo "========================================"
  echo "Iteration $i of $MAX_ITERATIONS"
  echo "========================================"
  echo "Started at: $(date)"
  echo ""

  run_agent

  echo ""
  echo "Finished at: $(date)"

  if grep -q "<promise>COMPLETE</promise>" "$OUTPUT_FILE"; then
    echo "========================================"
    echo "  ALL TASKS COMPLETE"
    echo "========================================"
    echo "Completed after $i iterations at $(date)"
    rm -f "$OUTPUT_FILE"
    exit 0
  fi

  false_count=$(grep -c '"passes": false' "$PLAN_FILE" 2>/dev/null || true)
  in_progress_count=$(grep -c '"passes": "in_progress"' "$PLAN_FILE" 2>/dev/null || true)
  true_count=$(grep -c '"passes": true' "$PLAN_FILE" 2>/dev/null || true)

  echo ""
  echo "Task Status: $true_count done, $in_progress_count in progress, $false_count remaining"

  if [ "${false_count:-0}" -eq 0 ] && [ "${in_progress_count:-0}" -eq 0 ]; then
    echo "========================================"
    echo "  ALL TASKS COMPLETE"
    echo "========================================"
    rm -f "$OUTPUT_FILE"
    exit 0
  fi

  echo ""
  echo "--- End of iteration $i ---"
  echo "Waiting 2 seconds..."
  echo ""
  sleep 2
done

echo "========================================"
echo "  MAX ITERATIONS REACHED"
echo "========================================"
echo "Reached max iterations ($MAX_ITERATIONS)"
rm -f "$OUTPUT_FILE"
exit 1
