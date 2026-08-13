import logging

from anthropic import AsyncAnthropic

from app.llm.base import ChatMessage, LLMProvider

# claude-opus-5 is the current flagship model as of this writing — verified
# against Anthropic's live model catalog while writing this file, not
# recalled from training data (model IDs on this provider change often
# enough that guessing is a real risk). Confirm against shared/models.md
# in the claude-api skill if this ever needs revisiting.
_MODEL = "claude-opus-5"

# claude-opus-5 supports up to 128K output tokens (streaming required above
# ~16K to avoid SDK HTTP timeouts). 16000 is comfortably under that timeout
# threshold while giving multi-file site generations enough room that a
# truncated mid-JSON response (the original cause of the chat 502s) is a lot
# less likely.
_MAX_TOKENS = 16000

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    async def generate(self, api_key: str, system_prompt: str, messages: list[ChatMessage]) -> str:
        client = AsyncAnthropic(api_key=api_key)
        response = await client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        if response.stop_reason == "max_tokens":
            logger.warning("Anthropic response truncated at max_tokens=%d", _MAX_TOKENS)
        return "".join(block.text for block in response.content if block.type == "text")
