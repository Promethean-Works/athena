"""The AI assistant: providers, model lists and chats (docs/mvp-design.md §4.5).

Everything here is admin only: the assistant reads the host, and providers hold keys.
"""

import json
import logging
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pydantic_ai import ToolDenied
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model
from sqlmodel import Session, col, select

from athena import audit
from athena.api.jobs import SSE_HEADERS
from athena.assistant import chat, questions
from athena.assistant import settings as ai_settings
from athena.assistant.context import window_for
from athena.assistant.kinds import BY_ID, KINDS, KindId, ProviderKind, secret_keys
from athena.assistant.plans import PlanStep, delete_plan, plan_of
from athena.assistant.providers import (
    ModelCache,
    ModelInfo,
    ProviderConfig,
    ProviderError,
    build_model,
    check_values,
    config_of,
    fetch_models,
    split_values,
)
from athena.assistant.settings import ModelRef
from athena.auth.deps import Authed, CurrentUser, DbSession, current_user
from athena.crypto import SecretBox, SecretError
from athena.db.models import AiConversation, AiProvider

log = logging.getLogger(__name__)


def require_admin(user: Annotated[CurrentUser, Depends(current_user)]) -> None:
    if not user.user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can use the assistant")


router = APIRouter(prefix="/assistant", tags=["assistant"], dependencies=[Depends(require_admin)])

ProviderId = Annotated[str, Path(pattern=r"^[a-f0-9]{16}$")]
ConversationId = Annotated[str, Path(pattern=r"^[a-f0-9]{16}$")]
Values = dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=4096)]]


def _box(request: Request) -> SecretBox:
    return request.app.state.secret_box


def _cache(request: Request) -> ModelCache:
    return request.app.state.model_cache


# ---------------------------------------------------------------- providers


class ProviderIn(BaseModel):
    kind: KindId
    name: str = Field(min_length=1, max_length=64)
    values: Values = {}


class ProviderUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    values: Values = {}
    """Secrets left empty keep their stored value."""


class ProviderOut(BaseModel):
    id: str
    kind: KindId
    name: str
    values: dict[str, str]
    """Non-secret settings only."""
    secrets_set: list[str]
    """Which secret fields have a stored value."""
    created_at: datetime


class ModelsOut(BaseModel):
    models: list[ModelInfo]
    error: str | None = None


class ProviderModels(ModelsOut):
    provider_id: str
    provider_name: str
    kind: KindId
    lists_models: bool


class TestOut(BaseModel):
    ok: bool
    message: str


def _out(row: AiProvider, box: SecretBox) -> ProviderOut:
    kind = BY_ID[row.kind]
    stored: list[str] = []
    if row.secrets:
        try:
            stored = sorted(json.loads(box.decrypt(row.secrets)))
        except SecretError:
            stored = []
    return ProviderOut(
        id=row.id,
        kind=kind.id,
        name=row.name,
        values=json.loads(row.config or "{}"),
        secrets_set=stored,
        created_at=row.created_at,
    )


def _get_provider(db: Session, provider_id: str) -> AiProvider:
    row = db.get(AiProvider, provider_id)
    if row is None or row.kind not in BY_ID:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such provider")
    return row


def _config(row: AiProvider, box: SecretBox) -> ProviderConfig:
    try:
        return config_of(row, box)
    except SecretError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


def _store(row: AiProvider, kind: ProviderKind, values: dict[str, str], box: SecretBox) -> None:
    try:
        check_values(kind, values)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    plain, secret = split_values(kind, values)
    row.config = json.dumps(plain)
    row.secrets = box.encrypt(json.dumps(secret)) if secret else None


@router.get("/kinds", operation_id="listAiProviderKinds")
def list_kinds() -> list[ProviderKind]:
    return KINDS


@router.get("/providers", operation_id="listAiProviders")
def list_providers(request: Request, db: DbSession) -> list[ProviderOut]:
    rows = db.exec(select(AiProvider).order_by(col(AiProvider.created_at))).all()
    return [_out(r, _box(request)) for r in rows if r.kind in BY_ID]


@router.post("/providers", operation_id="createAiProvider", status_code=status.HTTP_201_CREATED)
def create_provider(body: ProviderIn, request: Request, user: Authed, db: DbSession) -> ProviderOut:
    kind = BY_ID[body.kind]
    row = AiProvider(id=secrets.token_hex(8), kind=kind.id, name=body.name.strip())
    _store(row, kind, body.values, _box(request))
    db.add(row)
    audit.record(db, user.user.username, "ai.provider.create", f"{row.name} ({kind.id})")
    db.commit()
    db.refresh(row)
    return _out(row, _box(request))


@router.put("/providers/{provider_id}", operation_id="updateAiProvider")
def update_provider(
    provider_id: ProviderId, body: ProviderUpdate, request: Request, user: Authed, db: DbSession
) -> ProviderOut:
    row = _get_provider(db, provider_id)
    kind = BY_ID[row.kind]
    box = _box(request)
    values = dict(body.values)
    # Empty secrets keep what's stored (the form shows them as "Unchanged").
    if row.secrets:
        try:
            stored = json.loads(box.decrypt(row.secrets))
        except SecretError:
            stored = {}
        for key in secret_keys(kind):
            if not values.get(key) and stored.get(key):
                values[key] = stored[key]
    row.name = body.name.strip()
    _store(row, kind, values, box)
    db.add(row)
    audit.record(db, user.user.username, "ai.provider.edit", row.name)
    db.commit()
    _cache(request).drop(row.id)
    return _out(row, box)


@router.delete(
    "/providers/{provider_id}",
    operation_id="deleteAiProvider",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_provider(
    provider_id: ProviderId, request: Request, user: Authed, db: DbSession
) -> Response:
    row = _get_provider(db, provider_id)
    db.delete(row)
    settings = ai_settings.load(db)
    for attr in ("default_model", "title_model", "advisor_model"):
        ref: ModelRef | None = getattr(settings, attr)
        if ref and ref.provider_id == provider_id:
            setattr(settings, attr, None)
    ai_settings.save(db, settings)
    audit.record(db, user.user.username, "ai.provider.remove", row.name)
    db.commit()
    _cache(request).drop(provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _models(request: Request, row: AiProvider, refresh: bool) -> list[ModelInfo]:
    cache = _cache(request)
    if not refresh and (cached := cache.get(row.id)) is not None:
        return cached
    models = await fetch_models(_config(row, _box(request)), request.app.state.ai_transport)
    cache.put(row.id, models)
    return models


@router.post("/providers/{provider_id}/test", operation_id="testAiProvider")
async def test_provider(provider_id: ProviderId, request: Request, db: DbSession) -> TestOut:
    """Lists the provider's models, which proves the address and key work."""
    row = _get_provider(db, provider_id)
    try:
        models = await _models(request, row, refresh=True)
    except ProviderError as exc:
        return TestOut(ok=False, message=str(exc))
    if not BY_ID[row.kind].lists_models:
        return TestOut(ok=True, message="Connected. Type your deployment name as the model.")
    if not models:
        return TestOut(ok=True, message="Connected, but the provider lists no models.")
    usable = sum(m.tools is not False for m in models)
    count = f"{len(models)} model" + ("" if len(models) == 1 else "s")
    return TestOut(ok=True, message=f"Connected: {count}, {usable} can use tools.")


@router.get("/providers/{provider_id}/models", operation_id="listAiProviderModels")
async def provider_models(
    provider_id: ProviderId, request: Request, db: DbSession, refresh: bool = False
) -> ModelsOut:
    row = _get_provider(db, provider_id)
    try:
        return ModelsOut(models=await _models(request, row, refresh))
    except ProviderError as exc:
        return ModelsOut(models=[], error=str(exc))


@router.get("/models", operation_id="listAiModels")
async def all_models(request: Request, db: DbSession) -> list[ProviderModels]:
    """Every provider's models, for the model picker. A provider that fails still shows,
    with its error, so its model ids can be typed."""
    out = []
    for row in db.exec(select(AiProvider).order_by(col(AiProvider.created_at))).all():
        if row.kind not in BY_ID:
            continue
        kind = BY_ID[row.kind]
        try:
            models, error = await _models(request, row, refresh=False), None
        except (ProviderError, HTTPException) as exc:
            models, error = [], str(getattr(exc, "detail", exc))
        out.append(
            ProviderModels(
                provider_id=row.id,
                provider_name=row.name,
                kind=kind.id,
                lists_models=kind.lists_models,
                models=models,
                error=error,
            )
        )
    return out


# ---------------------------------------------------------------- conversations


class ConversationOut(BaseModel):
    id: str
    title: str
    model: ModelRef | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[chat.ChatMessage]
    running: bool
    usage: chat.ChatUsage
    """What the whole chat has used so far."""
    spend_limit_usd: float | None
    """Settings → AI's limit per chat, if any."""
    plan: list[PlanStep]
    """The assistant's plan for this chat (empty until it writes one)."""


class ConversationIn(BaseModel):
    model: ModelRef | None = None


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    model: ModelRef | None = None


class Decision(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    """The tool call's id."""
    approve: bool
    reason: str | None = Field(default=None, max_length=1000)
    """For a denial: what the model is told instead of the default."""


class ApprovalsIn(BaseModel):
    decisions: list[Decision] = Field(default_factory=list, max_length=100)
    """One per waiting action."""
    answers: list[questions.Answer] = Field(default_factory=list, max_length=20)
    """One per waiting question."""


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=32_000)
    model: ModelRef | None = None
    """The model to answer with; the chat's last model when empty."""


def _conv_out(row: AiConversation) -> ConversationOut:
    model = (
        ModelRef(provider_id=row.provider_id, model=row.model)
        if row.provider_id and row.model
        else None
    )
    return ConversationOut(
        id=row.id,
        title=row.title,
        model=model,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _get_conv(db: Session, user: CurrentUser, conversation_id: str) -> AiConversation:
    row = db.get(AiConversation, conversation_id)
    if row is None or row.user_id != user.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such chat")
    return row


def _turns(request: Request) -> chat.Turns:
    return request.app.state.assistant_turns


@router.get("/conversations", operation_id="listConversations")
def list_conversations(user: Authed, db: DbSession) -> list[ConversationOut]:
    rows = db.exec(
        select(AiConversation)
        .where(AiConversation.user_id == user.user.id)
        .order_by(col(AiConversation.updated_at).desc())
    ).all()
    return [_conv_out(r) for r in rows]


@router.post(
    "/conversations", operation_id="createConversation", status_code=status.HTTP_201_CREATED
)
def create_conversation(body: ConversationIn, user: Authed, db: DbSession) -> ConversationOut:
    model = body.model or ai_settings.load(db).default_model
    assert user.user.id is not None
    row = AiConversation(
        id=secrets.token_hex(8),
        user_id=user.user.id,
        provider_id=model.provider_id if model else None,
        model=model.model if model else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _conv_out(row)


@router.get("/conversations/{conversation_id}", operation_id="getConversation")
async def get_conversation(
    conversation_id: ConversationId, request: Request, user: Authed, db: DbSession
) -> ConversationDetail:
    row = _get_conv(db, user, conversation_id)
    conv = chat.load_history(row)
    messages = chat.transcript_messages(row, conv)
    return ConversationDetail(
        **_conv_out(row).model_dump(),
        messages=chat.ui_messages(
            messages, chat.pending_ids(conv), chat.summarizer(db), chat.waiting_questions(conv)
        ),
        running=_turns(request).get(row.id) is not None,
        usage=chat.usage_of(conv.usage if conv else None),
        spend_limit_usd=ai_settings.load(db).spend_limit_usd,
        plan=await plan_of(request.app.state.settings.data_dir, row.id),
    )


@router.patch("/conversations/{conversation_id}", operation_id="updateConversation")
def update_conversation(
    conversation_id: ConversationId, body: ConversationPatch, user: Authed, db: DbSession
) -> ConversationOut:
    row = _get_conv(db, user, conversation_id)
    if body.title is not None:
        row.title = body.title.strip()
    if body.model is not None:
        row.provider_id, row.model = body.model.provider_id, body.model.model
    db.add(row)
    db.commit()
    return _conv_out(row)


@router.delete(
    "/conversations/{conversation_id}",
    operation_id="deleteConversation",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: ConversationId, request: Request, user: Authed, db: DbSession
) -> Response:
    row = _get_conv(db, user, conversation_id)
    if _turns(request).get(row.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Stop the reply before deleting this chat")
    db.delete(row)
    db.commit()
    await delete_plan(request.app.state.settings.data_dir, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/conversations/{conversation_id}/messages",
    operation_id="sendMessage",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def send_message(
    conversation_id: ConversationId, body: MessageIn, request: Request, user: Authed, db: DbSession
) -> StreamingResponse:
    """Server-Sent Events for the reply: `text` and `reasoning` (`delta`, and `new` when a
    new block starts), `tool-call` (`id`, `name`, `args`), `tool-result` (`id`, `result`,
    `error`, `denied`), `approval` (`calls`: the actions waiting for Approve/Deny, each with `id`,
    `name`, `args`, `summary` and `destructive`), `question` (`ids`: the `ask_user_question`
    calls waiting for an answer), `plan` (`steps`: the chat's plan after the assistant
    changed it), `job` (`id` of the tool call, `job_id`, `title`: a job an approved action
    started), `title`, `usage`, `stopped`, `error` (`message`) and finally `done`. While
    actions or questions wait, a new message denies and declines them."""
    row = _get_conv(db, user, conversation_id)
    turns = _turns(request)
    if turns.get(row.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This chat is still answering")
    model = _model_for(request, db, row, body.model)
    _audit_skipped(db, user, row)
    settings = ai_settings.load(db)
    assert user.user.id is not None
    turn = turns.start(
        row.id,
        app=request.app,
        model=model,
        text=body.text,
        spend_limit=settings.spend_limit_usd,
        user_id=user.user.id,
        window=_window_of(request, db, row, model),
        title_model=(
            _title_model(request, db, settings, model) if row.title == chat.NEW_CHAT else None
        ),
        advisor_model=_advisor_model(request, db, settings),
    )
    return StreamingResponse(turn.stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post(
    "/conversations/{conversation_id}/approvals",
    operation_id="answerApprovals",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def answer_approvals(
    conversation_id: ConversationId,
    body: ApprovalsIn,
    request: Request,
    user: Authed,
    db: DbSession,
) -> StreamingResponse:
    """Answer everything a paused chat is waiting on, and continue it: Approve or Deny each
    action (approved actions run as you, and each decision is audited) and answer or decline
    each question. Streams the same events as sendMessage."""
    row = _get_conv(db, user, conversation_id)
    turns = _turns(request)
    if turns.get(row.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This chat is still answering")
    conv = chat.load_history(row)
    pending = conv.deferred_tool_requests if conv else None
    if pending is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing in this chat is waiting for you")
    calls = {c.tool_call_id: c for c in pending.approvals}
    decided = {d.id: d for d in body.decisions}
    answered = {a.id: a for a in body.answers}
    if set(decided) != set(calls) or set(answered) != questions.question_ids(pending):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Answer every waiting action and question, and only those",
        )
    resume = chat.Resume()
    for call_id, a in answered.items():
        try:
            resume.answers[call_id] = questions.result_for(pending, a)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    model = _model_for(request, db, row, None)
    settings = ai_settings.load(db)
    decisions = resume.approvals
    for call_id, d in decided.items():
        call = calls[call_id]
        what = chat.summarizer(db)(call.tool_name, chat.args_of(call)) or call.tool_name
        if d.approve:
            decisions[call_id] = True
        else:
            reason = (d.reason or "").strip()
            decisions[call_id] = ToolDenied(
                f"The admin denied this: {reason}" if reason else "The admin denied this."
            )
        action = "assistant.approve" if d.approve else "assistant.deny"
        audit.record(db, user.user.username, action, what, call.tool_name)
    assert user.user.id is not None
    turn = turns.start(
        row.id,
        app=request.app,
        model=model,
        text=None,
        resume=resume,
        spend_limit=settings.spend_limit_usd,
        user_id=user.user.id,
        window=_window_of(request, db, row, model),
        advisor_model=_advisor_model(request, db, settings),
    )
    return StreamingResponse(turn.stream(), media_type="text/event-stream", headers=SSE_HEADERS)


def _audit_skipped(db: Session, user: CurrentUser, row: AiConversation) -> None:
    """A new message denies the actions still waiting (see `chat._results`); record
    those denials like the ones answered on their card."""
    conv = chat.load_history(row)
    pending = conv.deferred_tool_requests if conv else None
    for call in pending.approvals if pending else []:
        what = chat.summarizer(db)(call.tool_name, chat.args_of(call)) or call.tool_name
        audit.record(
            db, user.user.username, "assistant.deny", what, f"{call.tool_name}, by a new message"
        )


def _model_for(
    request: Request, db: Session, row: AiConversation, chosen: ModelRef | None
) -> Model:
    """The model to answer with (the one picked, else the chat's last, else the default),
    remembered on the chat."""
    ref = chosen or (
        ModelRef(provider_id=row.provider_id, model=row.model)
        if row.provider_id and row.model
        else ai_settings.load(db).default_model
    )
    if ref is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pick a model first")
    model = _build(request, db, ref)
    row.provider_id, row.model = ref.provider_id, ref.model
    db.add(row)
    db.commit()
    return model


def _window_of(request: Request, db: Session, row: AiConversation, model: Model) -> chat.Window:
    """Looks up the chat model's context window when the turn starts (after `_model_for`
    saved the choice on the chat)."""
    provider = db.get(AiProvider, row.provider_id)
    assert provider is not None and row.model is not None
    cfg, model_id = _config(provider, _box(request)), row.model
    cache, transport = _cache(request), request.app.state.ai_transport

    async def tokens() -> int:
        return (await window_for(cfg, model_id, model, cache, transport)).tokens

    return tokens


def _title_model(
    request: Request, db: Session, settings: ai_settings.AiSettings, chat_model: Model
) -> Model:
    """Settings → AI's title model, else (or when it's gone) the chat's own."""
    if settings.title_model is None:
        return chat_model
    try:
        return _build(request, db, settings.title_model)
    except HTTPException as exc:
        log.info("title model unavailable, using the chat's: %s", exc.detail)
        return chat_model


def _advisor_model(request: Request, db: Session, settings: ai_settings.AiSettings) -> Model | None:
    """Settings → AI's advisor model; none (no `advisor` tool) when unset or unavailable."""
    if settings.advisor_model is None:
        return None
    try:
        return _build(request, db, settings.advisor_model)
    except HTTPException as exc:
        log.info("advisor model unavailable, chatting without it: %s", exc.detail)
        return None


def _build(request: Request, db: Session, ref: ModelRef) -> Model:
    provider = db.get(AiProvider, ref.provider_id)
    if provider is None or provider.kind not in BY_ID:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That model's provider was removed. Pick another model."
        )
    try:
        return build_model(_config(provider, _box(request)), ref.model)
    except (ProviderError, ValueError, UserError) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post(
    "/conversations/{conversation_id}/stop",
    operation_id="stopConversation",
    status_code=status.HTTP_204_NO_CONTENT,
)
def stop_conversation(
    conversation_id: ConversationId, request: Request, user: Authed, db: DbSession
) -> Response:
    row = _get_conv(db, user, conversation_id)
    turn = _turns(request).get(row.id)
    if turn is not None:
        turn.token.cancel()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
