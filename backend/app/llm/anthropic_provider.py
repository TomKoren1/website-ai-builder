from anthropic import AsyncAnthropic

from app.llm.base import ChatMessage, LLMProvider

# claude-opus-5 is the current flagship model as of this writing — verified
# against Anthropic's live model catalog while writing this file, not
# recalled from training data (model IDs on this provider change often
# enough that guessing is a real risk). Confirm against shared/models.md
# in the claude-api skill if this ever needs revisiting.
_MODEL = "claude-opus-5"


class AnthropicProvider(LLMProvider):
    async def generate(self, api_key: str, system_prompt: str, messages: list[ChatMessage]) -> str:
        client = AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return "".join(block.text for block in response.content if block.type == "text")
