"""
integrations/azure/openai_client.py
Thin async wrapper around the Azure OpenAI chat completions API.

Used by all agents via BaseAgent.chat().
Provides:
  - Structured output (JSON-mode) helper
  - Streaming helper
  - Token counting / cost estimation

Requires in .env:
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_KEY
  AZURE_OPENAI_API_VERSION   (default: 2024-02-15-preview)
  AZURE_OPENAI_DEPLOYMENT
"""

from __future__ import annotations
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator

from openai import AsyncAzureOpenAI, AsyncOpenAI

from config import settings

logger = logging.getLogger("finops.openai")


def get_client():
    """Return a configured async OpenAI client for Azure OpenAI or Foundry."""
    config_issue = settings.azure_openai_configuration_issue()
    if config_issue:
        raise RuntimeError(config_issue)
    if settings.openai_endpoint_family() == "azure_foundry":
        return AsyncOpenAI(
            api_key=settings.AZURE_OPENAI_KEY,
            base_url=settings.openai_v1_base_url(),
        )
    return AsyncAzureOpenAI(
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
    )


async def chat_completion(
    messages: List[Dict[str, str]],
    deployment: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    json_mode: bool = False,
) -> str:
    """
    Single-shot chat completion. Returns the assistant message text.

    Args:
        messages:    Full message list [{role, content}, ...]
        deployment:  Override default GPT-4o deployment
        temperature: Sampling temperature (0.0–1.0)
        max_tokens:  Max response tokens
        json_mode:   If True, instructs the model to respond only in JSON
    """
    client     = get_client()
    model      = deployment or settings.AZURE_OPENAI_DEPLOYMENT
    extra_args: Dict[str, Any] = {}

    if json_mode:
        extra_args["response_format"] = {"type": "json_object"}

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **extra_args,
    )

    content = response.choices[0].message.content or ""
    tokens  = response.usage.total_tokens if response.usage else 0
    logger.debug("OpenAI completion: model=%s tokens=%d", model, tokens)
    return content


async def chat_stream(
    messages: List[Dict[str, str]],
    deployment: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> AsyncGenerator[str, None]:
    """
    Streaming chat completion. Yields text chunks as they arrive.
    Use with Server-Sent Events for the chat UI.
    """
    client = get_client()
    model  = deployment or settings.AZURE_OPENAI_DEPLOYMENT

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


async def structured_completion(
    system_prompt: str,
    user_message: str,
    deployment: Optional[str] = None,
) -> str:
    """
    Convenience wrapper for JSON-mode structured output.
    Enforces the model to respond with a valid JSON object.
    """
    messages = [
        {"role": "system", "content": system_prompt + "\n\nRespond ONLY with a valid JSON object."},
        {"role": "user",   "content": user_message},
    ]
    return await chat_completion(
        messages=messages,
        deployment=deployment or settings.AZURE_OPENAI_DEPLOYMENT,
        json_mode=True,
        temperature=0.0,
    )
