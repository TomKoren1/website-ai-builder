import logging

from openai import AsyncOpenAI

from app.llm.base import ChatMessage, LLMProvider

# UNVERIFIED, unlike the Anthropic model ID: this project has no equivalent
# skill/live-catalog check for OpenAI, and OpenAI's lineup moves just as
# fast. Confirm the current flagship model before relying on this beyond
# local dev — do not assume this is still current.
_MODEL = "gpt-4o"

# Matches the Anthropic provider's cap — see anthropic_provider.py for why
# 8192 was too tight for multi-file site generations.
_MAX_TOKENS = 16000

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    async def generate(self, api_key: str, system_prompt: str, messages: list[ChatMessage]) -> str:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "system", "content": system_prompt}]
            + [{"role": m.role, "content": m.content} for m in messages],
        )
        if response.choices[0].finish_reason == "length":
            logger.warning("OpenAI response truncated at max_tokens=%d", _MAX_TOKENS)
        return response.choices[0].message.content or ""
