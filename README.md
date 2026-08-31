# AI Runbook Publisher

Generates Production Support Runbooks for Java Spring Boot services using local `idfc-coder` agent execution and publishes validated runbooks to Confluence.

## Local macOS Quick Start

### One-time Setup

```bash
git pull
python3 -m pip install -r requirements.txt
chmod +x run.command
```

### Launch Interactive Mode

```bash
./run.command
```

1. Enter your local Spring Boot repository path (e.g. `/Users/user/Documents/work/api-virtualization-service`).
2. Press Enter to use the default AI executable (`idfc-coder`).
3. IDFC Coder will open with its working directory set to your repository.
4. The generation task is automatically copied to your clipboard via `pbcopy`.
5. Click the IDFC Coder window, press **Cmd + V**, and press **Enter**.
6. If **PLAN MODE** appears, approve it.
7. If **EXECUTE MODE** asks to continue, type `Proceed`.
8. Wait for runbook generation to complete.
9. Output is saved to `runs/<service>/<timestamp>/RUNBOOK.md`.

---

## Deterministic service fact collection

Usage:

```bash
python run.py \
  --repo /path/to/service \
  --collect-facts
```

This mode:
- Performs deterministic Layer 1 fact extraction across build, config, APIs, Kafka, databases, downstream clients, health, and deployment descriptors.
- **No AI is called** (zero LLM calls, zero token budgets).
- Target repository remains strictly **read-only**.
- Output is written to `output/<service-name>/<commit-sha>/service-facts.json`.
- Runtime Config Portal values are **not guessed** (placeholders `${KEY}` and defaults `${KEY:default}` are preserved separately).
- Secret values are **never emitted** into output JSON.

---

## Terminal Mode (CLI)

You can also run directly from the command line:

```bash
python run.py --repo /path/to/service --dry-run
```

### Local Dry-Run Features
- **Zero API Keys Required**: Uses your existing local `idfc-coder` authentication (no Anthropic or OpenAI API keys needed).
- **Zero Confluence Credentials Required**: Fully generates and validates runbooks locally.
- **Context-Safe**: Does not concatenate repository source into giant prompts. `idfc-coder` searches and inspects the repository directly.
- **Non-Destructive**: Output and logs are written exclusively to `runs/<service>/<timestamp>/`. The target application repository remains strictly read-only.

---

## Repository inspection

Example:

```bash
python run.py \
  --repo /path/to/spring-service \
  --inspect-repo
```

This mode:
- Performs safe, read-only repository inspection and file verification
- Auto-derives service name, Git branch, commit SHA, remote origin, and working tree status
- Inspects repository structure without calling AI or idfc-coder
- Does not contact Confluence or require API credentials
- Does not modify the target repository

---

## Publishing to Confluence

When ready to publish validated runbooks to Confluence:

1. Configure your Confluence details in `config/config.yml` (or export environment variables):
   ```bash
   export CONFLUENCE_API_TOKEN="your_atlassian_api_token"
   ```

2. Run without `--dry-run`:
   ```bash
   python run.py --repo /path/to/service
   ```

### Manual Support Notes Preservation
Any human-maintained operational notes authored directly on the Confluence page between:
```html
<!-- MANUAL SUPPORT NOTES START -->
... your manual operational notes ...
<!-- MANUAL SUPPORT NOTES END -->
```
are automatically extracted and preserved across subsequent automated runbook runs.

---

## Command Line Options

```bash
python run.py --help
```

- `--repo PATH`: Path to local Java Spring Boot repository (*required*).
- `--service NAME`: Service name override (defaults to `spring.application.name` or folder name).
- `--environment ENV`: Target environment (default: `production`).
- `--version VER`: Application version (default: `latest`).
- `--commit SHA`: Git commit SHA override (defaults to `HEAD`).
- `--branch BRANCH`: Git branch override (defaults to current branch).
- `--config PATH`: Path to config YAML (default: `config/config.yml`).
- `--coder CMD`: AI coder executable (default: `idfc-coder` or `$IDFC_CODER_CMD`).
- `--mode [interactive|stdin|arg]`: Execution mode (default: `interactive` or `$IDFC_CODER_MODE`).
- `--dry-run`: Generate and validate locally without publishing to Confluence.
- `--inspect-repo`: Inspect repository structure without AI or Confluence.
- `--collect-facts`: Run deterministic fact collection without AI or Confluence.
- `--build-index`: Build deterministic code index without AI or Confluence.
- `--search-index "query"`: Search code index with keyword query.
- `--ask-repo "question"`: Ask a question about the repository using the tool-calling LLM agent.
- `--generate-runbook`: Directly generate and validate a Production Support Runbook using the selected generation engine.
- `--engine [api|idfc-coder|external-agent]`: Select the generation engine (default: `api` or config `generation.default_engine`).
- `--output-suffix SUFFIX`: Append suffix to output runbook filename (e.g. `--output-suffix api` -> `RUNBOOK-api.md`).
- `--agent-debug`: Print tool calls during agent investigation (omits source bodies and credentials).

---

## Flag-Based Generation Engines

The runbook generator uses a single, shared pipeline with pluggable generation engines:

### 1. API Mode (`--engine api`)
Uses `RepositoryAgent` with safe repository tools (`search_code`, `read_lines`, `list_files`, `get_service_facts`) and an organization-approved OpenAI-compatible LLM gateway.

```bash
export LLM_BASE_URL="https://your-approved-gateway.internal/v1"
export LLM_API_KEY="your-api-key"
export LLM_MODEL="gpt-4o"

python run.py \
  --repo /path/to/service \
  --generate-runbook \
  --engine api \
  --environment production \
  --dry-run \
  --agent-debug
```

### 2. IDFC-Coder Mode (`--engine idfc-coder`)
Launches the local `idfc-coder` CLI directly from inside the target repository working directory (`cwd`), preserving interactive SSO, clipboard tasks, and local tool capabilities.

```bash
python run.py \
  --repo /path/to/service \
  --generate-runbook \
  --engine idfc-coder \
  --dry-run
```

### 3. External Agent Mode (`--engine external-agent`)
A manual bridge for local testing with Codex, Antigravity, or other external AI coding assistants using a clean 3-step state machine:

```bash
# Step 1: Prepare Discovery Task
python run.py \
  --repo /path/to/service \
  --generate-runbook \
  --engine external-agent \
  --environment production \
  --dry-run
# Creates: output/<service>/<commit-short>/DISCOVERY_TASK.md
# External agent inspects repo and writes REPOSITORY_FINDINGS.md

# Step 2: Prepare Fresh Runbook Task
python run.py \
  --repo /path/to/service \
  --generate-runbook \
  --engine external-agent \
  --environment production \
  --dry-run
# Creates: output/<service>/<commit-short>/RUNBOOK_TASK.md
# Fresh external agent converts REPOSITORY_FINDINGS.md into RUNBOOK.md (without re-opening repo)

# Step 3: Common Validation
python run.py \
  --repo /path/to/service \
  --generate-runbook \
  --engine external-agent \
  --environment production \
  --dry-run
# Runs validator against generated RUNBOOK.md and outputs PASS/FAIL
```

---

## Interactive Repository Exploration Agent

```bash
export LLM_BASE_URL="https://your-approved-gateway.internal/v1"
export LLM_API_KEY="your-api-key"
export LLM_MODEL="gpt-4o"

python run.py \
  --repo /path/to/service \
  --ask-repo "How does this service consume Kafka messages?" \
  --agent-debug
```

- **Interactive Tool Use**: The agent iteratively invokes read-only repository tools (`search_code`, `list_files`, `read_lines`, `get_service_facts`) to gather source evidence before answering.
- **No Full-Repo Prompting**: The repository is never concatenated into a single prompt.
- **Enterprise Safety**: Endpoints must be organization-approved for private source code. No arbitrary commands, shells, or write operations are ever exposed to the LLM.
- **Evidence Verification**: All citations are mechanically validated against repository files and line boundaries.

---

## Build code index

```bash
python run.py \
  --repo /path/to/service \
  --build-index
```

- Index is keyed by the repository commit SHA — automatically rebuilt when the commit changes.
- No AI is called, no embeddings are generated.
- Repository stays strictly read-only.
- Output is persisted to `.runbook-index/<service-name>/<commit-sha>/`.

## Search code index

```bash
python run.py \
  --repo /path/to/service \
  --search-index "transaction timeout"
```

- Loads existing index (or builds it if missing).
- Returns top-ranked code chunks: source path, symbol, line range, score.
- No AI. No embeddings. No Confluence.
- Results are purely deterministic keyword + symbol + annotation matching.

---

## Running Automated Tests

```bash
pytest -v
```

---

## Generation Identity, Caching & Artifact Reuse

The publisher uses a deterministic three-way identity system to ensure reproducible artifacts and prevent redundant AI runs:

### 1. Distinct Identities
- **`generationKey`**: Deterministic SHA-256 fingerprint representing the logical runbook generation:
  $$\text{generationKey} = \text{SHA256}(\text{serviceId} + \text{sourceFingerprint} + \text{promptFingerprint} + \text{contractVersion} + \text{platformContext})$$
- **`attemptId`**: Unique execution identifier (`att-YYYYMMDD-HHMMSS-xxxxxx`) tracking individual execution attempts, diagnostic logs, and retries under the *same* `generationKey`.
- **`commitSha`**: Git commit metadata.

### 2. Local Dirty-Worktree Fingerprinting
`sourceFingerprint` deterministically hashes all relevant tracked and uncommitted local source, configuration, and resource files while ignoring non-source noise (`.git`, `build/`, `target/`, `.gradle/`, `node_modules/`, `.idea/`, virtual environments, outputs).
- Editing any Java or config file changes `sourceFingerprint` $\rightarrow$ triggers a new `generationKey` even without committing.
- Editing noise files (logs, build directories) does not change `sourceFingerprint`.

### 3. Reuse & Retry Semantics
- **`CACHE HIT`**: If an identical successful generation (`status == "COMPLETE"`) exists with all mandatory artifacts, the publisher reuses the existing runbook and skips invoking AI engines.
- **`CACHE MISS`**: If source code, prompts, or contracts change, a fresh generation begins under a new `generationKey`.
- **`RETRY`**: If a previous generation was interrupted or failed, a new `attemptId` is launched under the existing `generationKey`.
- **`--force`**: Forces a new generation attempt under the same `generationKey` without changing the logical identity:
  ```bash
  python run.py --repo /path/to/service --generate-runbook --engine idfc-coder --force
  ```

### 4. Output Structure
Artifacts are organized by logical generation and attempt diagnostics:
```text
output/
  <serviceId>/
    <generationKey>/
      generation-metadata.json
      service-facts.json
      REPOSITORY_FINDINGS.md
      RUNBOOK.md
      confluence-body.html
      RUNBOOK.html
      validation-report.txt
      generation-summary.json
      attempts/
        <attemptId>/
          attempt-metadata.json
          agent.log
          stderr.log
          stdout.log
```

