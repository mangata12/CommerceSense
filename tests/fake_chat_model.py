"""Deterministic model transport; LangChain executor and tools remain real."""

from typing import Any
from pydantic import Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    responses: list[Any]
    calls: list[Any] = Field(default_factory=list)
    cursor: int = 0

    @property
    def _llm_type(self):
        return "scripted-test-transport"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        response = self.responses[self.cursor]
        self.cursor += 1
        if isinstance(response, Exception):
            raise response
        return ChatResult(generations=[ChatGeneration(message=response)])


def tool_call(name, args, identifier="test-call"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": identifier, "type": "tool_call"}])
