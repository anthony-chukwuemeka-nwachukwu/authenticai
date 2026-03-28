"""
llm_client.py — Provider-agnostic LLM abstraction layer.

All three calls (Call 1, Call 2A, Call 2B) go through this module.
Switching providers requires only environment variable changes — no code changes.

Supported providers (set LLM_PROVIDER env var):
  anthropic  — Anthropic API directly (default)
  azure      — Azure OpenAI Service
  openai     — OpenAI API directly

Environment variables by provider
──────────────────────────────────
anthropic (default):
  LLM_PROVIDER=anthropic
  ANTHROPIC_API_KEY=sk-ant-...
  LLM_MODEL=claude-opus-4-5        (any Anthropic model string)

azure:
  LLM_PROVIDER=azure
  AZURE_OPENAI_API_KEY=...
  AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
  AZURE_OPENAI_DEPLOYMENT=<your-deployment-name>   (e.g. gpt-4o)
  AZURE_OPENAI_API_VERSION=2024-02-01              (optional, has default)

openai:
  LLM_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  LLM_MODEL=gpt-4o                 (any OpenAI model string)

Usage (in llm_calls.py):
  from llm_client import chat
  response_text = chat(system_prompt, user_prompt, max_tokens=512)
"""

import os
from dotenv import load_dotenv
load_dotenv()


def chat(system: str, user: str, max_tokens: int = 1024) -> str:
    """
    Send a system + user message to the configured LLM provider.
    Returns the assistant response as a plain string.
    Raises RuntimeError with clear instructions if configuration is missing.
    """
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()

    if provider == "anthropic":
        return _chat_anthropic(system, user, max_tokens)
    elif provider == "azure":
        return _chat_azure(system, user, max_tokens)
    elif provider == "openai":
        return _chat_openai(system, user, max_tokens)
    else:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER '{provider}'. "
            "Supported values: anthropic, azure, openai"
        )


# ── Anthropic ─────────────────────────────────────────────────────────────────

def _chat_anthropic(system: str, user: str, max_tokens: int) -> str:
    try:
        import anthropic as _anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY.\n"
            "Export: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    model = os.environ.get("LLM_MODEL", "claude-opus-4-5")
    client = _anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}]
    )
    return response.content[0].text.strip()


# ── Azure OpenAI ──────────────────────────────────────────────────────────────

def _chat_azure(system: str, user: str, max_tokens: int) -> str:
    try:
        from openai import AzureOpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

    missing = [k for k, v in {
        "AZURE_OPENAI_API_KEY": api_key,
        "AZURE_OPENAI_ENDPOINT": endpoint,
        "AZURE_OPENAI_DEPLOYMENT": deployment,
    }.items() if not v]

    if missing:
        raise RuntimeError(
            f"LLM_PROVIDER=azure requires: {', '.join(missing)}\n"
            "Example:\n"
            "  export AZURE_OPENAI_API_KEY=...\n"
            "  export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/\n"
            "  export AZURE_OPENAI_DEPLOYMENT=gpt-4o"
        )

    client = AzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )

    response = client.chat.completions.create(
        model=deployment,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ]
    )
    return response.choices[0].message.content.strip()


# ── OpenAI ────────────────────────────────────────────────────────────────────

def _chat_openai(system: str, user: str, max_tokens: int) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed. Run: pip install openai")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LLM_PROVIDER=openai requires OPENAI_API_KEY.\n"
            "Export: export OPENAI_API_KEY=sk-..."
        )

    model = os.environ.get("LLM_MODEL", "gpt-4o")
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ]
    )
    return response.choices[0].message.content.strip()
