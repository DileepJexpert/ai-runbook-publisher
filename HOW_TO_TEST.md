# How to Test ai-runbook-publisher

This document is the master setup, execution, and verification guide for running `ai-runbook-publisher` locally or in an enterprise environment (e.g. on macOS / Linux / Windows using `idfc-coder` or other generation engines).

---

## 1. Publisher Setup

Open your terminal in the `ai-runbook-publisher` directory and execute:

```bash
# ============================================================
# A. PUBLISHER SETUP
# ============================================================

# Go to the ai-runbook-publisher folder opened in VS Code / terminal
cd /Users/dileep.maurya/YOUR_PATH/ai-runbook-publisher

# Confirm location
pwd

# Check Python version (Python 3.10+ required)
python3 --version

# Check IDFC Coder availability
which idfc-coder

# Create virtual environment (only if not already created)
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Confirm Python path from active virtual environment
which python
python --version

# Upgrade pip
python -m pip install --upgrade pip

# Install publisher dependencies
python -m pip install -r requirements.txt

# Run all automated tests
pytest -v

# Check publisher CLI
python run.py --help
```

> **Note:** If `pytest -v` passes (all unit and integration tests green), the publisher installation is verified and ready.

---

## 2. Verify Target Spring Boot Repository

Pick a real Spring Boot repository to test against. The target application must be an actual Git clone so the publisher can resolve commit, branch, and origin metadata.

```bash
# ============================================================
# B. VERIFY TARGET SPRING BOOT REPOSITORY
# ============================================================

export TARGET_REPO="/Users/dileep.maurya/Documents/work/my-spring-service"

cd "$TARGET_REPO"

# Confirm it is a Git repository
git status

# Check current branch
git branch --show-current

# Check commit SHA
git rev-parse HEAD

# Check remote repository URL
git remote -v
```

---

## 3. Return to Publisher Directory

```bash
# ============================================================
# C. RETURN TO RUNBOOK PUBLISHER
# ============================================================

cd /Users/dileep.maurya/YOUR_PATH/ai-runbook-publisher

source .venv/bin/activate
```

---

## 4. Deterministic Pre-Tests (No AI Involved)

Before involving AI or coder models, verify repository access and deterministic fact extraction:

### Step 4.1: Inspect Repository Metadata
```bash
# ============================================================
# D. TEST REPOSITORY INSPECTION - NO AI
# ============================================================

python run.py \
  --repo "$TARGET_REPO" \
  --inspect-repo
```

### Step 4.2: Collect Service Facts
```bash
# ============================================================
# E. COLLECT SERVICE FACTS - NO AI
# ============================================================

python run.py \
  --repo "$TARGET_REPO" \
  --collect-facts
```

These steps verify that repository access, Git inspection, and deterministic static analysis (controllers, properties, Kafka, DB, actuator) work without external dependencies.

---

## 5. Full Two-Pass Runbook Generation with IDFC-Coder

Run the complete two-pass pipeline with `idfc-coder` in dry-run mode (Confluence publication will NOT be triggered):

```bash
# ============================================================
# F. FULL RUNBOOK TEST WITH IDFC-CODER
# CONFLUENCE WILL NOT BE PUBLISHED
# ============================================================

python run.py \
  --repo "$TARGET_REPO" \
  --generate-runbook \
  --engine idfc-coder \
  --environment production \
  --dry-run
```

---

## 6. Target Architecture & Execution Pipeline

The execution follows a clean two-pass decoupled architecture:

```text
Target Spring Boot Repo
        ↓
service-facts.json (deterministic facts)
        ↓
IDFC Coder Discovery Pass (Pass 1)
        ↓
REPOSITORY_FINDINGS.md
        ↓
FIRST IDFC CODER CONTEXT ENDS
        ↓
Fresh IDFC Coder Invocation (Pass 2 - Fresh Context)
        ↓
RUNBOOK.md
        ↓
Lightweight Deterministic Validator
        ↓
RUNBOOK.html (Standalone rendered HTML)
        ↓
STOP (Confluence: NOT PUBLISHED in dry-run)
```

### Key Safety & Isolation Principles
1. **Fresh Context in Pass 2**: The runbook writer starts in a fresh context with `REPOSITORY_FINDINGS.md` and `service-facts.json`. It does NOT continue exploring Java source files.
2. **Interactive/SSO Approval**: Because `idfc-coder` is interactive / SSO-based, approve any tool execution prompts in the coder session as requested.
3. **No Confluence Writes**: In `--dry-run`, zero write requests are sent to Confluence.

---

## 7. Expected CLI Output

Upon successful completion, the CLI reports:

```text
Production Support Runbook Generation
-------------------------------------

Service: <service-name>
Commit: <commit-sha>
Environment: production

Deterministic facts loaded: YES
Generation engine: idfc-coder
Tool calls: <count>

Discovery:
COMPLETE
Findings: output/<service>/<commit-short>/REPOSITORY_FINDINGS.md

Runbook:
output/<service>/<commit-short>/RUNBOOK.md

Validation: PASSED

HTML:
GENERATED
output/<service>/<commit-short>/RUNBOOK.html

Evidence:
None

Confluence:
NOT PUBLISHED (dry-run)
```

---

## 8. Inspecting Generated Artifacts

### List generated artifacts:
```bash
find output -name "REPOSITORY_FINDINGS.md" -o -name "RUNBOOK.md" -o -name "RUNBOOK.html"
```

### Open the rendered HTML runbook locally:
```bash
# macOS
open output/<service>/<commit-short>/RUNBOOK.html

# Or automatically find and open the latest:
open "$(find output -name RUNBOOK.html | head -1)"
```

```bash
# Linux
xdg-open "$(find output -name RUNBOOK.html | head -1)"
```

```powershell
# Windows (PowerShell)
Start-Process (Get-ChildItem -Path output -Filter RUNBOOK.html -Recurse | Select-Object -First 1).FullName
```

---

## 9. Troubleshooting & Support

If any step fails:
1. Do not apply multiple random fixes.
2. Inspect the generated error report in `output/<service>/<commit-short>/validation-report.txt` or `generation-summary.json`.
3. Capture the exact terminal output for diagnosis.
