# Master Testing Guide for ai-runbook-publisher

This document is the concrete, step-by-step test execution and troubleshooting guide for running `ai-runbook-publisher` on your enterprise environment (e.g. macOS with IDFC Coder).

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

## 4. Run Two-Pass Generation with IDFC Coder

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

---

## 7. Troubleshooting & Diagnostic Guide

### Problem 1: Script pauses or waits between Pass 1 and Pass 2
- **Cause**: `--mode interactive` launches an interactive terminal session where IDFC Coder waits for human keystrokes (`Cmd+V`, `Enter`, or tool approvals).
- **Remediation**: Use non-interactive mode:
  ```bash
  python run.py \
    --repo /Users/dileep.maurya/Documents/API-Integration-workspace/beneficiary-validation-service \
    --engine idfc-coder \
    --mode arg \
    --dry-run \
    --force
  ```

### Problem 2: `RUNBOOK.html` or `confluence-body.html` is not found
- **Cause**: HTML rendering is only triggered **after `RUNBOOK.md` exists and passes deterministic safety validation**. If Pass 1 or Pass 2 fails, or if validation fails, HTML is intentionally omitted to avoid unvalidated output.
- **Remediation**: Check which step completed:
  ```bash
  find output/beneficiary-validation-service -type f
  ```
  - If only `service-facts.json` exists $\rightarrow$ Pass 1 did not complete.
  - If `REPOSITORY_FINDINGS.md` exists but `RUNBOOK.md` does not $\rightarrow$ Pass 2 did not complete.
  - If `RUNBOOK.md` exists but `validation-report.txt` contains `FAILED` $\rightarrow$ Check validation errors in `validation-report.txt`.

### Problem 3: CLI prints `CACHE HIT: Reusing existing runbook`
- **Cause**: A previous generation for this exact commit and prompt already succeeded (`COMPLETE`).
- **Remediation**: Pass `--force` to bypass the cache and run a fresh generation:
  ```bash
  python run.py --repo ... --engine idfc-coder --mode arg --dry-run --force
  ```

### Problem 4: `Executable not found: 'idfc-coder'`
- **Cause**: `idfc-coder` is not in your current `$PATH`.
- **Remediation**:
  1. Find the binary location:
     ```bash
     which idfc-coder
     ```
  2. Pass the explicit path via CLI or environment variable:
     ```bash
     python run.py --coder /full/path/to/idfc-coder ...
     # OR
     export IDFC_CODER_CMD=/full/path/to/idfc-coder
     ```

### Problem 5: `Validation: FAILED` in CLI output
- **Cause**: The generated `RUNBOOK.md` failed safety validation rules (e.g., missing required sections, unpopulated `[TODO]` placeholders, raw Java code blocks, or affirmative dangerous recommendations like `Replay Kafka messages`).
- **Remediation**: Read the validation failure reasons:
  ```bash
  cat output/beneficiary-validation-service/*/validation-report.txt
  ```

### Problem 6: `DirtyWorkingTreeError: PIPELINE mode requires a clean working tree`
- **Cause**: Uncommitted changes in target repo when running in `--execution-mode pipeline`.
- **Remediation**: In local developer testing, use `--execution-mode local` (the default). If testing pipeline mode, commit your changes in the target repo first.

### Problem 7: `ModuleNotFoundError: No module named 'click'`
- **Cause**: Virtual environment is not activated or dependencies are not installed.
- **Remediation**:
  ```bash
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
