from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    name: str = "Base Agent"
    description: str = "Abstract base agent"
    system_prompt: str = "You are a helpful AI assistant."

    def __init__(self):
        self._calls_today = 0
        self._errors_today = 0
        self._enabled = True
        self._last_run: Optional[float] = None
        self._client = None

        config_issue = settings.azure_openai_configuration_issue()
        if not config_issue:
            try:
                from integrations.azure.openai_client import get_client

                self._client = get_client()
                logger.info(
                    "Agent '%s' initialized with %s",
                    self.name,
                    settings.openai_endpoint_family(),
                )
            except Exception as exc:
                logger.warning("Agent '%s' OpenAI init failed: %s", self.name, exc)
        else:
            logger.info("Agent '%s' initialized without Azure OpenAI: %s", self.name, config_issue)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        logger.info("Agent '%s' %s", self.name, "enabled" if value else "disabled")

    @property
    def calls_today(self) -> int:
        return self._calls_today

    @property
    def uptime_pct(self) -> float:
        total = self._calls_today + self._errors_today
        if total == 0:
            return 100.0
        return round((self._calls_today / total) * 100, 1)

    async def chat(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]] | None = None,
        context: str | None = None,
        use_fast_model: bool = False,
    ) -> str:
        if not self._enabled:
            raise RuntimeError(f"Agent '{self.name}' is currently disabled.")

        if self._client is None:
            self._calls_today += 1
            self._last_run = time.time()
            return self._unavailable_response(context)

        system = self.system_prompt
        if context:
            system += f"\n\n--- LIVE AZURE CONTEXT ---\n{context}\n--- END CONTEXT ---"

        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        if conversation_history:
            messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        try:
            response = await self._client.chat.completions.create(
                model=settings.AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
                temperature=0.2,
                max_tokens=1024,
            )
            self._calls_today += 1
            self._last_run = time.time()
            return response.choices[0].message.content or ""
        except Exception as exc:
            self._errors_today += 1
            logger.error("[%s] LLM call failed: %s: %s", self.name, type(exc).__name__, exc)
            return self._unavailable_response(context)

    def _unavailable_response(self, context: str | None = None) -> str:
        response = (
            f"{self.name} cannot generate a natural-language answer because Azure OpenAI "
            "is not configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY, and "
            "AZURE_OPENAI_DEPLOYMENT to enable the chatbot."
        )
        if context:
            response += "\n\nLive context fetched:\n" + context
        return response

    @abstractmethod
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def _build_json_prompt(self, instruction: str) -> str:
        return (
            f"{instruction}\n\n"
            "Respond only with a valid JSON object. "
            "No markdown, no preamble, no explanation outside the JSON."
        )

    def reset_daily_counters(self):
        self._calls_today = 0
        self._errors_today = 0
