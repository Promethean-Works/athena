"""The chat as the UI sees it: messages, their parts and usage (docs/design/assistant.md).

Kept apart from `chat` so the API can describe its responses without importing pydantic-ai.
"""

from typing import Any, Literal

from pydantic import BaseModel

NEW_CHAT = "New chat"
"""The title a chat has until its first message names it."""


class ChatPart(BaseModel):
    type: Literal["text", "reasoning", "tool"]
    text: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    args: Any = None
    result: str | None = None
    """The tool's result as JSON or text, cut to RESULT_CHARS."""
    error: str | None = None
    state: Literal["running", "done", "error", "approval", "question", "denied"] | None = None
    """`approval`: waiting for Approve/Deny. `question`: an `ask_user_question` waiting for
    the admin's answer. `denied`: the admin said no."""
    summary: str | None = None
    """For tools that need approval: the action in one sentence."""
    destructive: bool = False
    job_id: str | None = None
    """The job an approved action started (GET /api/jobs/{id} while it's kept)."""
    draft: bool = False
    """Text the model revised afterwards ("Double-check answers"); the UI folds it away."""


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    parts: list[ChatPart]


class ChatUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    """USD, when the model's prices are known."""
