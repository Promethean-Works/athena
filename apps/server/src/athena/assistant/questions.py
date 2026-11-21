"""Multiple-choice questions from the assistant (docs/design/assistant.md, part D stage 2).

The harness `AskUser` gives the model `ask_user_question`. With no answerer, a question pauses
the run like an approval does: the run ends with `DeferredToolRequests` (the question is in
`calls`, of kind `question`), the saved `Conversation` keeps it, and the chat UI shows a
question card. The admin's answer comes back through `POST .../approvals` with the actions'
decisions, and resumes the run with the harness's own rendering of the answer.

The model writes the questions, so a prompt injection could have it ask for a password: the
card says the question comes from the assistant and never looks like a sign-in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pydantic_ai import DeferredToolRequests
    from pydantic_ai.capabilities import AbstractCapability

MAX_CUSTOM = 500
"""A typed answer is cut to this many characters."""

DECLINED_BY_NEW_MESSAGE = (
    "The admin didn't answer this question; they sent a new message instead. "
    "Read it before asking again."
)


class QuestionAnswer(BaseModel):
    header: str = Field(min_length=1, max_length=100)
    """The question's header, as the model wrote it."""
    selected: list[str] = Field(default_factory=list, max_length=6)
    """The labels picked; empty when `custom` is given."""
    custom: str | None = Field(default=None, max_length=MAX_CUSTOM)
    """The admin's own answer instead of an option."""


class Answer(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    """The `ask_user_question` call's id."""
    declined: bool = False
    """Skip the questions: the model is told the admin declined."""
    answers: list[QuestionAnswer] = Field(default_factory=list, max_length=10)
    """One per question when not declined."""


def question_ids(requests: DeferredToolRequests | None) -> frozenset[str]:
    """The `ask_user_question` calls a paused chat is waiting on."""
    from pydantic_ai_harness.ask_user import TOOL_NAME

    if requests is None:
        return frozenset()
    return frozenset(
        c.tool_call_id
        for c in requests.calls
        if c.tool_name == TOOL_NAME and requests.kind(c.tool_call_id) == "question"
    )


def result_for(requests: DeferredToolRequests, answer: Answer) -> Any:
    """What the model gets for the admin's answer. Raises ValueError when the answer doesn't
    fit the questions (an unknown header or label, two picks on a single choice)."""
    from pydantic_ai_harness.ask_user import (
        AskUserAnswer,
        AskUserRequest,
        AskUserResponse,
        ask_user_result,
    )

    call = next(c for c in requests.calls if c.tool_call_id == answer.id)
    request = AskUserRequest.from_tool_call(call)
    if answer.declined:
        return ask_user_result(request, AskUserResponse(cancelled=True))
    response = AskUserResponse(
        answers=tuple(
            AskUserAnswer(header=a.header, custom_answer=a.custom.strip())
            if a.custom and a.custom.strip()
            else AskUserAnswer(header=a.header, selected=tuple(a.selected))
            for a in answer.answers
        )
    )
    return ask_user_result(request, response)


def question_capabilities() -> list[AbstractCapability[Any]]:
    from pydantic_ai_harness import AskUser

    return [AskUser(answerer=None)]
