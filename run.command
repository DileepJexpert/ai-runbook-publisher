#!/bin/bash
set -e

# Navigate to script directory
cd "$(dirname "$0")"

echo "============================================="
echo "          AI SUPPORT RUNBOOK GENERATOR       "
echo "============================================="
echo ""

read -r -p "Local service repository folder: " REPO_PATH
if [ -z "$REPO_PATH" ]; then
    echo "Error: Repository path is required."
    exit 1
fi

read -r -p "AI executable [idfc-coder]: " CODER_CMD
CODER_CMD="${CODER_CMD:-idfc-coder}"

echo ""
python3 run.py --repo "$REPO_PATH" --coder "$CODER_CMD" --mode interactive --dry-run
