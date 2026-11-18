"""Chat turns: run the agent for one user message, stream typed events, save the history
(docs/mvp-design.md §4.5).

A turn runs in its own task and keeps going if the browser goes away, so the answer is
saved either way. Stopping uses pydantic-ai's CancellationToken, which keeps what the
model had already said. When durable execution is on and a pgtask/Postgres database is
configured, the turn is enqueued as a pgtask task: every model request and tool call is
checkpointed, so an interrupted run resumes from its last completed step instead of
repeating paid work.
"""

import asyncio
import contextlib
import copy
import dataclasses
import json
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import FastAPI
from pgtask import Client, EnqueueRequest, Task, TaskRegistry
from pydantic import BaseModel
from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    CancellationToken,
    Conversation,
    ConversationTypeAdapter,
    DeferredToolRequests,
    DeferredToolResults,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RunCancelled,
    ToolDenied,
    UsageLimits,
    capture_run_messages,
)
from pydantic_ai.capabilities import AbstractCapability, Caching
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage
from sqlmodel import Session, col, select

from athena import audit
from athena.assistant import actions
from athena.assistant import settings as ai_settings
from athena.assistant.approval_review import review_capabilities as approval_review_capabilities
from athena.assistant.browser_use import browser_use_capabilities
from athena.assistant.code_mode import code_mode_capabilities
from athena.assistant.coding_stack import CODING_INSTRUCTIONS, coding_stack_capabilities
from athena.assistant.compaction import TranscriptRecorder, compaction_capabilities
from athena.assistant.delegation import (
    advisor_capabilities,
    background_capabilities,
    background_result,
    delegation_capabilities,
    is_started_notice,
    workflow_capabilities,
)
from athena.assistant.docker_sandbox import docker_sandbox_capabilities
from athena.assistant.durable_execution import durable_execution_capabilities
from athena.assistant.integrations import integration_toolsets
from athena.assistant.knowledge import is_memory_snapshot, knowledge_capabilities
from athena.assistant.mcp import mcp_toolsets
from athena.assistant.persistence import persistence_capabilities
from athena.assistant.plans import PLAN_TOOL, plan_of, planning_capabilities
from athena.assistant.questions import (
    DECLINED_BY_NEW_MESSAGE,
    question_capabilities,
    question_ids,
)
from athena.assistant.review import review_capabilities, starts_review
from athena.assistant.robustness import robustness_capabilities
from athena.assistant.safety import safety_capabilities
from athena.assistant.settings import McpServer
from athena.assistant.tools import Deps, shell_provider, toolset_for
from athena.assistant.web_research import web_research_capabilities
from athena.assistant.workspace import shell_capabilities
from athena.auth.deps import CurrentUser
from athena.db.models import AiConversation, AiIntegration, AuthSession, User
from athena.platform.capabilities import CapabilityManifest

log = logging.getLogger(__name__)

TITLE_LENGTH = 60
TITLE_WAIT = 10
"""Seconds to wait for a generated title after the reply ends before using the first line."""
RESULT_CHARS = 4000
"""Tool results shown in the UI are cut to this; the model still gets all of it."""

INSTRUCTIONS = """\
You are Athena's assistant. Athena is a self-hosted home server control panel: apps \
(Docker Compose projects), an app store, host packages, a terminal, files, shares and \
cloud storage. You help the server's admin understand and run this server.

- Use your tools to look things up instead of guessing. Only the tools you have exist on \
this host; if something isn't available, say so and point to the page in Athena that \
would handle it.
- Tools that change something (install, deploy, start, stop, remove, package and file \
changes) need the admin's approval: calling one shows them an Approve/Deny card with the \
exact action, and it runs only if they approve. So don't ask "shall I?" in text first; \
call the tool, and the card is the question.
- Never guess ids or names: look them up first (list_file_locations and list_files, \
list_apps, list_package_managers, search_store and get_store_app for an install's fields), \
so the call is right the first time.
- When you need the admin to choose (which app, which folder, keep or replace), ask with \
ask_user_question and concrete options instead of asking in text. For a task with several \
steps, keep a plan with write_plan and update each step's status as you go.
- For a broad look-up whose details you won't need afterwards (every app's logs, a folder \
tree, comparing several store apps), hand it to the investigator with delegate_task: a \
helper that can only read, with a task that says everything it needs (it can't see this \
chat). Set run_in_background to start two at once or to keep working meanwhile.
- When an action is denied, don't call it again unless the admin asks; ask what they want \
instead. Report what an approved action did, including failures from its log.
- Be brief and concrete. Use Markdown for lists, tables and code.
"""


def _host_instructions(manifest: CapabilityManifest) -> str:
    return f"This server runs {manifest.os_version} ({manifest.os}, {manifest.arch})."


agent: Agent[Deps, str | DeferredToolRequests] = Agent(
    deps_type=Deps,
    output_type=[str, DeferredToolRequests],
    instructions=[INSTRUCTIONS],
    capabilities=[Caching()],
    name="athena",
)


title_agent: Agent[None, str] = Agent(
    output_type=str,
    instructions=(
        "Write a title of at most six words for a chat that starts with the user's message. "
        "Use the message's language. Reply with the title only: no quotes, no Markdown, "
        "no final period."
    ),
    name="athena-title",
)


async def generate_title(model: Model, text: str) -> str | None:
    """A short title for a new chat from its first message, or None when the model gives
    nothing usable. Errors are left to the caller."""
    result = await title_agent.run(
        text[:2000], model=model, usage_limits=UsageLimits(request_limit=1)
    )
    return clean_title(result.output)


QUOTES = "\"'\u201c\u201d\u2018\u2019 "
"""Straight and curly quotes, and spaces: what models wrap titles in."""


def clean_title(raw: str) -> str | None:
    """The first line of a model's answer, without Markdown, quotes or a final period."""
    line = next((ln for ln in raw.splitlines() if ln.strip()), "")
    line = line.strip().strip("#*_`" + QUOTES).removeprefix("Title:")
    line = line.strip().rstrip(".").strip(QUOTES)
    return _title(line) if line else None


# ---------------------------------------------------------------- UI messages


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


def _result_text(content: Any) -> str:
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    return text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + "…"


def _job_of(content: Any) -> str | None:
    job = content.get("job_id") if isinstance(content, dict) else None
    return job if isinstance(job, str) else None


def _user_text(part: UserPromptPart) -> str:
    if isinstance(part.content, str):
        return part.content
    return "\n".join(c for c in part.content if isinstance(c, str))


Summarize = Callable[[str, Any], str | None]


def ui_messages(
    messages: list[ModelMessage],
    pending: frozenset[str] = frozenset(),
    summarize: Summarize = lambda name, args: None,
    questions: frozenset[str] = frozenset(),
) -> list[ChatMessage]:
    """The stored history as chat bubbles: user prompts, and one assistant message per
    reply with its text, reasoning and tool calls (with their results). Calls in
    `pending` are waiting for the admin's approval, and those in `questions` for an
    answer."""
    out: list[ChatMessage] = []
    tools: dict[str, ChatPart] = {}
    started: set[str] = set()
    """Background calls whose result hasn't arrived yet."""
    current: ChatMessage | None = None
    for i, msg in enumerate(messages):
        if isinstance(msg, ModelRequest):
            if current is not None and starts_review(msg):
                for part in current.parts:
                    if part.type == "text":
                        part.draft = True
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    if is_memory_snapshot(part):
                        continue
                    if found := background_result(part):
                        call_id, text, failed = found
                        if (tool := tools.get(call_id)) is not None:
                            tool.result = None if failed else _result_text(text)
                            tool.error = _result_text(text) if failed else None
                            tool.state = "error" if failed else "done"
                            started.discard(call_id)
                        continue
                    current = None
                    out.append(
                        ChatMessage(
                            id=f"m{i}",
                            role="user",
                            parts=[ChatPart(type="text", text=_user_text(part))],
                        )
                    )
                elif isinstance(part, ToolReturnPart) and part.tool_call_id in tools:
                    tool = tools[part.tool_call_id]
                    if is_started_notice(part.content):
                        started.add(part.tool_call_id)  # its real result comes later
                        continue
                    tool.result = _result_text(part.content)
                    tool.job_id = _job_of(part.content)
                    tool.state = (
                        "error"
                        if part.outcome == "failed"
                        else "denied"
                        if part.outcome == "denied"
                        else "done"
                    )
                elif isinstance(part, RetryPromptPart) and part.tool_call_id in tools:
                    tool = tools[part.tool_call_id]
                    tool.error = _result_text(part.content)
                    tool.state = "error"
        elif isinstance(msg, ModelResponse):
            if current is None:
                current = ChatMessage(id=f"m{i}", role="assistant", parts=[])
                out.append(current)
            for part in msg.parts:
                if isinstance(part, TextPart) and part.content:
                    current.parts.append(ChatPart(type="text", text=part.content))
                elif isinstance(part, ThinkingPart) and part.content:
                    current.parts.append(ChatPart(type="reasoning", text=part.content))
                elif isinstance(part, ToolCallPart):
                    args = args_of(part)
                    tool = ChatPart(
                        type="tool",
                        tool_call_id=part.tool_call_id,
                        tool_name=part.tool_name,
                        args=args,
                        state=(
                            "approval"
                            if part.tool_call_id in pending
                            else "question"
                            if part.tool_call_id in questions
                            else "running"
                        ),
                        summary=summarize(part.tool_name, args),
                        destructive=actions.is_destructive(part.tool_name, args),
                    )
                    tools[part.tool_call_id] = tool
                    current.parts.append(tool)
    for call_id in started:
        # A run that paused or stopped cancels its background calls.
        tools[call_id].state = "error"
        tools[call_id].error = STOPPED_IN_BACKGROUND
    return out


STOPPED_IN_BACKGROUND = (
    "Stopped before it finished: the reply ended while it ran in the background."
)


def args_of(part: ToolCallPart) -> Any:
    try:
        return part.args_as_dict()
    except (ValueError, TypeError):
        return part.args


# ---------------------------------------------------------------- history


def load_history(row: AiConversation) -> Conversation | None:
    if not row.history:
        return None
    try:
        return ConversationTypeAdapter.validate_json(row.history)
    except ValueError:
        log.warning("conversation %s has unreadable history; starting over", row.id)
        return None


def transcript_messages(row: AiConversation, conv: Conversation | None) -> list[ModelMessage]:
    """The whole chat as the admin saw it: the saved transcript once compaction has
    shortened the history, else the history itself."""
    if row.transcript:
        try:
            return list(ModelMessagesTypeAdapter.validate_json(row.transcript))
        except ValueError:
            log.warning("conversation %s has an unreadable transcript; showing history", row.id)
    return list(conv.messages) if conv else []


def new_transcript(
    row: AiConversation,
    previous: Conversation | None,
    recorder: TranscriptRecorder,
    final: list[ModelMessage],
) -> str | None:
    """The transcript to save after a turn: None while nothing was ever compacted (the
    history is the transcript), else the old one plus what this turn added."""
    if row.transcript is None and not recorder.compacted:
        return None
    full = [*transcript_messages(row, previous), *recorder.finish(final)]
    return ModelMessagesTypeAdapter.dump_json(full).decode()


def pending_ids(conv: Conversation | None) -> frozenset[str]:
    """The tool calls a paused chat is waiting on the admin for."""
    if conv is None or conv.deferred_tool_requests is None:
        return frozenset()
    return frozenset(c.tool_call_id for c in conv.deferred_tool_requests.approvals)


def waiting_questions(conv: Conversation | None) -> frozenset[str]:
    """The questions a paused chat is waiting on the admin to answer."""
    return question_ids(conv.deferred_tool_requests if conv else None)


Decisions = dict[str, bool | ToolDenied]
"""Tool call id -> approved, or the denial (with what the model is told)."""


@dataclass
class Resume:
    """The admin's answers to a paused chat: Approve/Deny per action, and the tool result
    per question (`questions.result_for`). Every waiting call needs one."""

    approvals: Decisions = field(default_factory=dict)
    answers: dict[str, Any] = field(default_factory=dict)


NEW_CHAT = "New chat"
"""The title a chat has until its first message names it."""

DENIED_BY_NEW_MESSAGE = "The admin didn't approve this; they sent a new message instead."


# ---------------------------------------------------------------- running a turn


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@dataclass
class Turn:
    """One running reply. Events go to whoever is listening; the task saves the result."""

    conversation_id: str
    token: CancellationToken = field(default_factory=CancellationToken)
    queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None

    def emit(self, event: str, data: Any) -> None:
        self.queue.put_nowait(sse(event, data))

    async def stream(self) -> AsyncIterator[str]:
        while (item := await self.queue.get()) is not None:
            yield item


class ChatUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    """USD, when the model's prices are known."""


def usage_of(usage: RunUsage | None) -> ChatUsage:
    if usage is None:
        return ChatUsage()
    cost = usage.cost
    return ChatUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost=float(cost) if cost is not None else None,
    )


async def _run(
    turn: Turn,
    *,
    app: FastAPI,
    model: Model,
    text: str | None,
    resume: Resume | None,
    spend_limit: float | None,
    user_id: int,
    title_model: Model | None,
    advisor_model: Model | None,
    review_model: Model | None,
    window: "Window",
) -> None:
    db_factory = app.state.db
    manifest = await app.state.capabilities.get()
    for db in db_factory.session():
        row = db.get(AiConversation, turn.conversation_id)
        user = db.get(User, user_id)
        assert row is not None and user is not None
        previous = load_history(row)
        results = _results(previous, resume)
        # Title generation moved to after the turn completes (sequential), to avoid
        # concurrent requests to the same local provider (e.g., Ollama).
        # Actions call route helpers, which take the signed-in user; the session isn't used.
        current = CurrentUser(user=user, session=AuthSession(user_id=user_id))
        ai = ai_settings.load(db)
        integration_rows = db.exec(
            select(AiIntegration).order_by(col(AiIntegration.created_at))
        ).all()
        deps = Deps(
            app=app,
            db=db,
            user=current,
            manifest=manifest,
            emit=turn.emit,
            shell_commands=tuple(ai.shell_commands) if ai.shell_enabled else (),
            memory=ai.memory_enabled,
        )
        limits = turn_limits(previous, spend_limit)
        recorder = TranscriptRecorder(start=len(previous.messages) if previous else 0)
        window_tokens = await _window_tokens(window)
        compaction = compaction_capabilities(window_tokens, recorder)
        data_dir = app.state.settings.data_dir
        extras = [
            *workflow_capabilities(model, manifest, data_dir, window_tokens, ai.mcp_servers),
            *planning_capabilities(app.state.settings.data_dir, turn.conversation_id),
            *question_capabilities(),
            *advisor_capabilities(advisor_model),
            *review_capabilities(ai.refine_answers),
            *approval_review_capabilities(review_model, ai.review_tool_calls),
            *docker_sandbox_capabilities(ai.docker_sandbox_enabled, deps.manifest),
            *durable_execution_capabilities(ai.durable_execution_enabled),
            *coding_stack_capabilities(ai.coding_stack_enabled, data_dir, tuple(ai.shell_commands)),
            *code_mode_capabilities(ai.code_mode_enabled),
            *browser_use_capabilities(ai.browser_use_enabled),
        ]
        saved: Conversation | None = None
        compacted_ok = True
        try:
            with capture_run_messages() as captured:
                saved = await _stream(
                    turn,
                    db,
                    previous,
                    results,
                    text,
                    model,
                    deps,
                    limits,
                    [
                        *extras,
                        *compaction,
                        *web_research_capabilities(
                            ai.web_research_enabled,
                            os.environ.get("EXA_API_KEY"),
                        ),
                    ],
                    [
                        *mcp_toolsets(ai.mcp_servers),
                        *integration_toolsets(integration_rows, app.state.secret_box),
                    ],
                    ai.mcp_servers,
                    CODING_INSTRUCTIONS if ai.coding_stack_enabled else "",
                )
        except RunCancelled as exc:
            saved = Conversation(messages=list(exc.all_messages()), usage=exc.usage or RunUsage())
            if exc.conversation_id:
                saved.conversation_id = exc.conversation_id
            turn.emit("stopped", {})
        except UsageLimitExceeded as exc:
            # The turn's work is dropped, but what it cost is kept, so the spend limit
            # holds: the next message is refused before it spends anything.
            saved = _with_spend(previous, captured)
            compacted_ok = False  # the history is the one the turn started with
            turn.emit("error", {"message": _limit_message(exc, spend_limit)})
        except Exception as exc:  # the model's errors are for the person to read
            log.warning("assistant turn failed: %s", exc)
            turn.emit("error", {"message": _readable(exc)})
        if saved is not None:
            if compacted_ok:
                row.transcript = new_transcript(row, previous, recorder, list(saved.messages))
            row.history = ConversationTypeAdapter.dump_json(saved).decode()
            if text and row.title == NEW_CHAT and title_model is not None:
                # Generate title sequentially after the main turn completes.
                # This avoids concurrent requests to the same provider (especially local ones).
                # Errors are caught and logged; fall back to the message text.
                try:
                    generated = await generate_title(title_model, text)
                except Exception as exc:
                    log.info("couldn't generate a chat title: %s", _readable(exc))
                    generated = None
                row.title = generated or _title(text)
                turn.emit("title", {"title": row.title})
            row.updated_at = datetime.now(UTC)
            db.add(row)
            db.commit()
            turn.emit("usage", usage_of(saved.usage).model_dump())
        turn.emit("done", {})


Window = Callable[[], Awaitable[int]]
"""Looks up the model's context window (`context.window_for`) when the turn starts."""

WINDOW_UNKNOWN = 8_192
"""Used when looking the window up fails outright, which shouldn't happen."""


async def _window_tokens(window: Window) -> int:
    try:
        return await window()
    except Exception as exc:  # compaction with a small guess beats a failed turn
        log.warning("couldn't look up the context window: %s", exc)
        return WINDOW_UNKNOWN


TURN_REQUESTS = 25
TURN_TOOL_CALLS = 50


def turn_limits(previous: Conversation | None, spend_limit: float | None) -> UsageLimits:
    """Limits for one turn. pydantic-ai checks them against the whole chat's usage, so
    the per-turn counts start from what the chat has used; the spend limit is for the
    whole chat (§4.5)."""
    used = previous.usage if previous else RunUsage()
    return UsageLimits(
        request_limit=used.requests + TURN_REQUESTS,
        tool_calls_limit=used.tool_calls + TURN_TOOL_CALLS,
        cost_limit=Decimal(str(spend_limit)) if spend_limit else None,
    )


async def _stream(
    turn: Turn,
    db: Session,
    previous: Conversation | None,
    results: DeferredToolResults | None,
    text: str | None,
    model: Model,
    deps: Deps,
    limits: UsageLimits,
    extras: list[AbstractCapability[Any]],
    mcp: list[MCPToolset[Any]] = (),
    mcp_servers: list[McpServer] = (),
    coding_instructions: str = "",
) -> Conversation | None:
    """Runs the agent, forwarding its events; returns the chat to save. `extras` are the
    turn's workflow, planning, questions, advisor, review and compaction (compaction last, so
    it measures and records the request as everything else left it). `mcp` are the configured
    MCP server toolsets, fresh per turn so concurrent runs never share a connection."""
    saved: Conversation | None = None
    data_dir = deps.app.state.settings.data_dir
    async with agent.run_stream_events(
        text,
        conversation=previous,
        model=model,
        deps=deps,
        toolsets=[*toolset_for(deps.manifest, deps.shell_commands), *mcp],
        capabilities=[
            *robustness_capabilities(data_dir, after_repair=background_capabilities()),
            *safety_capabilities(),
            *delegation_capabilities(model, deps.manifest, data_dir, mcp_servers),
            *knowledge_capabilities(
                deps.app.state.settings.data_dir,
                user_id=deps.user.user.id,
                memory=deps.memory,
                record=_flagged_recorder(deps),
            ),
            *persistence_capabilities(deps.app.state.settings.data_dir),
            *shell_capabilities(shell_provider(deps.manifest), deps.shell_commands),
            *extras,
        ],
        instructions=[
            _host_instructions(deps.manifest),
            *([coding_instructions] if coding_instructions else []),
        ],
        usage_limits=limits,
        cancellation_token=turn.token,
        deferred_tool_results=results,
    ) as events:
        async for event in events:
            _forward(turn, event)
            if _changes_plan(event):
                plan = await plan_of(deps.app.state.settings.data_dir, turn.conversation_id)
                turn.emit("plan", {"steps": [s.model_dump() for s in plan]})
            if isinstance(event, AgentRunResultEvent):
                saved = event.result.conversation
                output = event.result.output
                if isinstance(output, DeferredToolRequests):
                    if output.approvals:
                        turn.emit("approval", _approvals_out(db, output))
                    if asked := question_ids(output):
                        turn.emit("question", {"ids": sorted(asked)})
    return saved


def _changes_plan(event: Any) -> bool:
    return (
        isinstance(event, FunctionToolResultEvent)
        and isinstance(event.part, ToolReturnPart)
        and event.part.tool_name == PLAN_TOOL
    )


def _flagged_recorder(deps: Deps) -> Callable[[str, str], None]:
    """Audits memory and skills the scanner flagged (`knowledge.AuditingScanner`)."""

    def record(source: str, summary: str) -> None:
        audit.record(deps.db, deps.username, "assistant.injection", source, summary[:500])

    return record


def _with_spend(previous: Conversation | None, captured: list[ModelMessage]) -> Conversation:
    """The chat as it was, plus the usage of the responses a stopped run got."""
    kept = previous or Conversation()
    usage = copy.copy(kept.usage)
    for msg in captured[len(kept.messages) :]:
        if isinstance(msg, ModelResponse):
            usage.incr(msg.usage)
            usage.requests += 1
    return dataclasses.replace(kept, usage=usage)


def usd(amount: float) -> str:
    """$2.00, or $0.005 when two decimals would hide the amount."""
    return f"${amount:.2f}" if round(amount, 2) == amount else f"${amount:g}"


def _limit_message(exc: UsageLimitExceeded, spend_limit: float | None) -> str:
    text = str(exc)
    if "cost_limit" in text and spend_limit:
        return (
            f"This chat reached its spend limit of {usd(spend_limit)}. Start a new chat, "
            "or raise the limit in Settings → AI."
        )
    if "request_limit" in text:
        return (
            f"Stopped: this reply needed more than {TURN_REQUESTS} model requests. "
            "Try a narrower question."
        )
    if "tool_calls_limit" in text:
        return (
            f"Stopped: this reply needed more than {TURN_TOOL_CALLS} tool calls. "
            "Try a narrower question."
        )
    return "Stopped: " + text.split(". Consider raising the limit")[0]


def _results(previous: Conversation | None, resume: Resume | None) -> DeferredToolResults | None:
    """What to resume a paused chat with: the admin's answers, or, when they sent a new
    message instead, a denial of every waiting action and a decline of every question (a
    run can't start with calls left unanswered)."""
    pending = previous.deferred_tool_requests if previous else None
    if pending is None:
        return None
    if resume is None:
        resume = Resume(
            approvals={
                c.tool_call_id: ToolDenied(DENIED_BY_NEW_MESSAGE) for c in pending.approvals
            },
            answers={c.tool_call_id: DECLINED_BY_NEW_MESSAGE for c in pending.calls},
        )
    return pending.build_results(approvals=resume.approvals, calls=resume.answers)


def summarizer(db: Session) -> Summarize:
    return lambda name, args: actions.summarize(db, name, args)


def _approvals_out(db: Session, requests: DeferredToolRequests) -> dict[str, Any]:
    return {
        "calls": [
            {
                "id": c.tool_call_id,
                "name": c.tool_name,
                "args": args_of(c),
                "summary": actions.summarize(db, c.tool_name, args_of(c)),
                "destructive": actions.is_destructive(c.tool_name, args_of(c)),
            }
            for c in requests.approvals
        ]
    }


def _forward(turn: Turn, event: Any) -> None:
    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, TextPart):
            turn.emit("text", {"delta": part.content, "new": True})
        elif isinstance(part, ThinkingPart):
            turn.emit("reasoning", {"delta": part.content, "new": True})
    elif isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta) and delta.content_delta:
            turn.emit("text", {"delta": delta.content_delta})
        elif isinstance(delta, ThinkingPartDelta) and delta.content_delta:
            turn.emit("reasoning", {"delta": delta.content_delta})
    elif isinstance(event, FunctionToolCallEvent):
        part = event.part
        turn.emit(
            "tool-call", {"id": part.tool_call_id, "name": part.tool_name, "args": args_of(part)}
        )
    elif isinstance(event, FunctionToolResultEvent):
        part = event.part
        if isinstance(part, ToolReturnPart):
            if is_started_notice(part.content):
                return  # the row keeps running; `BackgroundResults` sends the real result
            failed = part.outcome == "failed"
            turn.emit(
                "tool-result",
                {
                    "id": part.tool_call_id,
                    "result": _result_text(part.content),
                    "error": _result_text(part.content) if failed else None,
                    "denied": part.outcome == "denied",
                },
            )
        elif isinstance(part, RetryPromptPart):
            turn.emit(
                "tool-result",
                {
                    "id": part.tool_call_id,
                    "result": None,
                    "error": _result_text(part.content),
                    "denied": False,
                },
            )


def _readable(exc: Exception) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text if len(text) <= 500 else text[:500] + "…"


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= TITLE_LENGTH else line[: TITLE_LENGTH - 1].rstrip() + "…"


class Turns:
    """Running turns by conversation id: one at a time per chat."""

    def __init__(self) -> None:
        self._turns: dict[str, Turn] = {}
        # Set by `create_app` when a pgtask/Postgres database URL is configured: turns are
        # then enqueued as pgtask tasks so they're durable (checkpointed) across crashes.
        self.pgtask_client: Client | None = None
        self.pgtask_registry: TaskRegistry | None = None
        self._pgtask_executors: dict[str, Callable[[Task], Awaitable[None]]] = {}

    def get(self, conversation_id: str) -> Turn | None:
        turn = self._turns.get(conversation_id)
        if turn and turn.task and turn.task.done():
            self._turns.pop(conversation_id, None)
            return None
        return turn

    def register_pgtask_handlers(self) -> None:
        """Register the pgtask task that runs each durable assistant turn.

        The handler runs inside a pgtask task, so `current_task_steps()` is not None and
        the `PGTaskDurability` capability checkpoints every model request and tool call.
        """
        if self.pgtask_registry is None:
            return

        @self.pgtask_registry.task("athena.assistant.turn")
        async def handle_turn(task: Task, payload: dict[str, Any]) -> None:
            cid = payload.get("conversation_id") if isinstance(payload, dict) else None
            executor = self._pgtask_executors.pop(cid, None) if cid else None
            if executor is None:
                log.warning("pgtask turn %s has no executor to run", task.id)
                return
            await executor(task)

    def _run_durable(self, conversation_id: str) -> Awaitable[None]:
        """Enqueue this turn as a pgtask task and wait for it to complete.

        `turn.task` is this awaitable, so stopping/shutdown can cancel it and the turn
        stays "live" while its events stream to the browser.
        """
        assert self.pgtask_client is not None

        async def run() -> None:
            handle = await self.pgtask_client.enqueue(
                EnqueueRequest(
                    task_name="athena.assistant.turn",
                    payload={"conversation_id": conversation_id},
                )
            )
            try:
                await handle.result()
            finally:
                self._pgtask_executors.pop(conversation_id, None)

        return run()

    def start(
        self,
        conversation_id: str,
        *,
        app: FastAPI,
        model: Model,
        text: str | None,
        spend_limit: float | None,
        user_id: int,
        window: Window,
        resume: Resume | None = None,
        title_model: Model | None = None,
        advisor_model: Model | None = None,
        review_model: Model | None = None,
        durable: bool = False,
    ) -> Turn:
        """Start one turn. When `durable` and a pgtask client are configured, the turn is
        run inside a pgtask task (checkpointed, resumable); otherwise it runs inline."""
        turn = Turn(conversation_id)

        async def body() -> None:
            try:
                await _run(
                    turn,
                    app=app,
                    model=model,
                    text=text,
                    resume=resume,
                    spend_limit=spend_limit,
                    user_id=user_id,
                    title_model=title_model,
                    advisor_model=advisor_model,
                    review_model=review_model,
                    window=window,
                )
            except Exception:
                log.exception("assistant turn crashed")
                turn.emit("error", {"message": "The assistant failed. See the server log."})
                turn.emit("done", {})
            finally:
                turn.queue.put_nowait(None)
                self._turns.pop(conversation_id, None)

        self._turns[conversation_id] = turn
        if durable and self.pgtask_client is not None and self.pgtask_registry is not None:
            self._pgtask_executors[conversation_id] = body
            turn.task = asyncio.create_task(self._run_durable(conversation_id))
        else:
            turn.task = asyncio.create_task(body())
        return turn

    async def stop_all(self) -> None:
        for turn in list(self._turns.values()):
            turn.token.cancel()
            if turn.task:
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await asyncio.wait_for(turn.task, 5)
