# AI Runbook Publisher

Generates a Production Support Runbook from a Java Spring Boot repository and creates or updates one Confluence page per service.

## Install

```bash
pip install -r requirements.txt
python run.py --help
```

Set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` after changing `ai.provider`) and, for publishing, `CONFLUENCE_API_TOKEN`. Edit `config/config.yml` with the Confluence URL, space key, and username.

## Local dry run

Dry runs call the configured AI provider but need no Confluence credentials:

```bash
python run.py --repo /path/to/repo --service payments-integration-service --environment production --version 2.3.1 --commit a3f9c2d --branch main --dry-run
```

## CI/CD

```bash
#!/bin/bash
# ci-runbook.sh — call after a successful deployment
python run.py \
  --repo "$REPO_PATH" \
  --service "$SERVICE_NAME" \
  --environment "$DEPLOY_ENV" \
  --version "$APP_VERSION" \
  --commit "$GIT_COMMIT" \
  --branch "$GIT_BRANCH" \
  --config /etc/runbook/config.yml

if [ $? -ne 0 ]; then
  echo "Runbook publish failed - continuing deployment"
fi
```

If publication fails after generation, the Markdown is retained as `runbook-{service}-{timestamp}.md` in the current directory.
