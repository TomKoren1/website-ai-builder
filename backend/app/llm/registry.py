from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.openai_provider import OpenAIProvider

# Keys match the `provider` column on api_keys (see app/models.py).
_PROVIDERS: dict[str, LLMProvider] = {
    "anthropic": AnthropicProvider(),
    "openai": OpenAIProvider(),
}


def get_provider(name: str) -> LLMProvider:
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise ValueError(f"Unknown LLM provider: {name!r}. Supported: {list(_PROVIDERS)}")
