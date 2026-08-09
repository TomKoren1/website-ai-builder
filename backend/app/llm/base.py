from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, api_key: str, system_prompt: str, messages: list[ChatMessage]) -> str:
        """Returns the assistant's reply text for one turn."""
        ...
