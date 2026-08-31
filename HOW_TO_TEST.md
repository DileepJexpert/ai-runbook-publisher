# Master Testing Guide for ai-runbook-publisher

This document is the concrete, step-by-step test execution guide for running `ai-runbook-publisher` on your enterprise environment (e.g. macOS with IDFC Coder).

---

## 1. Publisher Environment Setup

Open the terminal in VS Code inside your `ai-runbook-publisher` folder:

```bash
# ============================================================
# A. PUBLISHER ENVIRONMENT SETUP
# ============================================================

# Confirm location
pwd

# Check Python version (Python 3.10+ required)
python3 --version

# Check IDFC Coder availability
which idfc-coder

# Create virtual environment (if not already created)
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Confirm Python path
which python
python --version

# Upgrade pip
python -m pip install --upgrade pip

# Install publisher dependencies
python -m pip install -r requirements.txt

# Run automated tests to verify clean installation
pytest -v

# Check CLI options
python run.py --help
```

---

## 2. Verify Target Service Repository

Verify the target service repository (`beneficiary-validation-service`):

```bash
# ============================================================
# B. VERIFY TARGET SERVICE REPOSITORY
# ============================================================

export TARGET_REPO="/Users/dileep.maurya/Documents/API-Integration-workspace/beneficiary-validation-service"

cd "$TARGET_REPO"

# Confirm git status and commit
git status
git branch --show-current
git rev-parse HEAD
git remote -v
```

---

## 3. Deterministic Pre-Tests (No AI Involved)

Return to the `ai-runbook-publisher` directory and run static discovery:

```bash
# ============================================================
# C. RETURN TO PUBLISHER & RUN DETERMINISTIC PRE-CHECKS
# ============================================================

# Return to publisher directory
cd - || cd /Users/dileep.maurya/ai-runbook-publisher

source .venv/bin/activate

# 1. Test repository inspection (No AI)
python run.py \
  --repo /Users/dileep.maurya/Documents/API-Integration-workspace/beneficiary-validation-service \
  --inspect-repo

# 2. Test deterministic service fact collection (No AI)
python run.py \
  --repo /Users/dileep.maurya/Documents/API-Integration-workspace/beneficiary-validation-service \
  --collect-facts
```

---

## 4. Run Two-Pass Generation with IDFC Coder (Non-Interactive)

To run the complete two-pass pipeline automatically without babysitting or manual copy-pasting, test the non-interactive modes:

### Recommended: Pass Task as File Argument (`--mode arg`)
```bash
# ============================================================
# D1. NON-INTERACTIVE TWO-PASS GENERATION (--mode arg)
# Runs Pass 1 -> REPOSITORY_FINDINGS.md -> Pass 2 -> RUNBOOK.md -> HTML
# Zero manual resume, Enter, or copy-paste required
# ============================================================

python run.py \
  --repo /Users/dileep.maurya/Documents/API-Integration-workspace/beneficiary-validation-service \
  --engine idfc-coder \
  --mode arg \
  --dry-run \
  --force
```

### Alternative: Pipe Task via STDIN (`--mode stdin`)
If `--mode arg` is not supported by your IDFC Coder CLI binary, try standard input piping:
```bash
# ============================================================
# D2. NON-INTERACTIVE TWO-PASS GENERATION (--mode stdin)
# Pipes task content directly to IDFC Coder process
# ============================================================

python run.py \
  --repo /Users/dileep.maurya/Documents/API-Integration-workspace/beneficiary-validation-service \
  --engine idfc-coder \
  --mode stdin \
  --dry-run \
  --force
```

### Interactive Mode (`--mode interactive`)
Used for step-by-step interactive debugging with clipboard (`pbcopy`) banner:
```bash
# ============================================================
# D3. INTERACTIVE MODE (DEBUGGING ONLY)
# ============================================================

python run.py \
  --repo /Users/dileep.maurya/Documents/API-Integration-workspace/beneficiary-validation-service \
  --engine idfc-coder \
  --mode interactive \
  --dry-run \
  --force
```

---

## 5. Execution Pipeline Overview

```text
Pass 1: Discovery Pass
   ↓
Reads service-facts.json + Java source code
   ↓
Produces REPOSITORY_FINDINGS.md
   ↓
FIRST SESSION ENDS (Clean Context Boundary)
   ↓
Pass 2: Runbook Writing Pass (Fresh Session)
   ↓
Reads REPOSITORY_FINDINGS.md ONLY (No Java re-scan)
   ↓
Produces RUNBOOK.md
   ↓
Lightweight Deterministic Safety Validator
   ↓
Generates RUNBOOK.html & confluence-body.html
   ↓
STOP (Confluence: NOT PUBLISHED in dry-run)
```

---

## 6. Inspecting Generated Artifacts

After execution completes:

```bash
# List all generated files for the service
find output/beneficiary-validation-service -type f

# Check the generation summary
cat output/beneficiary-validation-service/*/generation-summary.json

# Check the deterministic validation report
cat output/beneficiary-validation-service/*/validation-report.txt

# Open the rendered HTML runbook in your default browser (macOS)
open "$(find output/beneficiary-validation-service -name RUNBOOK.html | head -1)"
```
