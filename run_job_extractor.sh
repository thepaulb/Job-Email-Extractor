#!/bin/bash
# Run the job link extractor using the project's virtual environment.
# Usage:
#   Manual:    ./run_job_extractor.sh
#   Launchd:   called automatically by com.paulbarton.jobextractor.plist

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
EXTRACTOR="$SCRIPT_DIR/job_link_extractor.py"
LOG_FILE="$SCRIPT_DIR/daily_jobs/extractor.log"

# Ensure output folder exists
mkdir -p "$SCRIPT_DIR/daily_jobs"

# Run the extractor, logging output
echo "=== Run started: $(date) ===" >> "$LOG_FILE"
"$VENV_PYTHON" "$EXTRACTOR" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "=== Run finished: $(date) (exit code: $EXIT_CODE) ===" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit $EXIT_CODE
