from openai import AsyncOpenAI

from app.llm.base import ChatMessage, LLMProvider

# UNVERIFIED, unlike the Anthropic model ID: this project has no equivalent
# skill/live-catalog check for OpenAI, and OpenAI's lineup moves just as
# fast. Confirm the current flagship model before relying on this beyond
# local dev — do not assume this is still current.
_MODEL = "gpt-4o"


class OpenAIProvider(LLMProvider):
    async def generate(self, api_key: str, system_prompt: str, messages: list[ChatMessage]) -> str:
        client = AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=_MODEL,
            max_tokens=8192,
            messages=[{"role": "system", "content": system_prompt}]
            + [{"role": m.role, "content": m.content} for m in messages],
        )
        return response.choices[0].message.content or ""
