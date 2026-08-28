"""Provider-neutral AI call for runbook generation."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

LOGGER = logging.getLogger(__name__)


def generate_runbook(repo_content: str, prompt_template: str, pipeline_metadata: dict, config: dict) -> str:
    values = {
        "SERVICE_NAME": pipeline_metadata.get("service_name", ""),
        "APP_VERSION": pipeline_metadata.get("app_version", ""),
        "ENVIRONMENT": pipeline_metadata.get("environment", ""),
        "COMMIT_SHA": pipeline_metadata.get("commit_sha", ""),
        "TIMESTAMP": pipeline_metadata.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "BRANCH": pipeline_metadata.get("branch", ""),
    }
    prompt = prompt_template
    for key, value in values.items():
        prompt = prompt.replace("{" + key + "}", str(value))
    prompt = f"{prompt}\n\nREPOSITORY CONTENT:\n{repo_content}\n\nGenerate the Production Support Runbook now."
    ai_config = config.get("ai", {})
    provider = ai_config.get("provider", "anthropic").lower()
    model = ai_config.get("model") or ("claude-sonnet-4-6" if provider == "anthropic" else "gpt-4o")
    LOGGER.info("Starting %s AI call using %s", provider, model)
    try:
        if provider == "anthropic":
            from anthropic import Anthropic
            client = Anthropic(api_key=config.get("anthropic", {}).get("api_key"))
            response = client.messages.create(model=model, max_tokens=int(ai_config.get("max_tokens", 8000)), messages=[{"role": "user", "content": prompt}])
            result = "".join(block.text for block in response.content if hasattr(block, "text"))
            LOGGER.info("AI call complete; input=%s output=%s", getattr(response.usage, "input_tokens", "unknown"), getattr(response.usage, "output_tokens", "unknown"))
        elif provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=config.get("openai", {}).get("api_key"))
            response = client.chat.completions.create(model=model, max_tokens=int(ai_config.get("max_tokens", 8000)), messages=[{"role": "user", "content": prompt}])
            result = response.choices[0].message.content or ""
            LOGGER.info("AI call complete; usage=%s", response.usage)
        else:
            raise ValueError("ai.provider must be either 'anthropic' or 'openai'")
    except Exception as exc:
        LOGGER.error("AI API failure: %s", exc)
        raise RuntimeError(f"Runbook generation failed using {provider}: {exc}") from exc
    if not result.strip():
        raise RuntimeError("AI returned an empty runbook response")
    if len(result) < 500:
        LOGGER.warning("AI response is unusually short (%d characters)", len(result))
    return result.strip()
