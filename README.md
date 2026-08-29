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
- `--agent-debug`: Print tool calls during agent investigation (omits source bodies and credentials).

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
