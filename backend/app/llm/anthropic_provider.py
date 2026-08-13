import logging

from anthropic import AsyncAnthropic

from app.llm.base import ChatMessage, LLMProvider

# claude-opus-5 is the current flagship model as of this writing — verified
# against Anthropic's live model catalog while writing this file, not
# recalled from training data (model IDs on this provider change often
# enough that guessing is a real risk). Confirm against shared/models.md
# in the claude-api skill if this ever needs revisiting.
_MODEL = "claude-opus-5"

# claude-opus-5 supports up to 128K output tokens. A "build out several full
# pages" request can genuinely need tens of thousands of tokens (each page is
# a complete HTML/CSS/JS file inside one JSON blob) — 16000 still truncated
# mid-JSON on a 4-page request. 64000 gives real headroom; the SDK requires
# streaming for anything much above ~16K to avoid client-side HTTP timeouts,
# which is why this uses client.messages.stream(...) instead of .create(...).
_MAX_TOKENS = 64000

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    async def generate(self, api_key: str, system_prompt: str, messages: list[ChatMessage]) -> str:
        client = AsyncAnthropic(api_key=api_key)
        async with client.messages.stream(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        ) as stream:
            response = await stream.get_final_message()
        if response.stop_reason == "max_tokens":
            logger.warning("Anthropic response truncated at max_tokens=%d", _MAX_TOKENS)
        return "".join(block.text for block in response.content if block.type == "text")
