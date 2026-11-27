"use client"

import * as React from "react"

import { useLatest } from "@/hooks/use-latest"

import {
  api,
  errorMessage,
  getCsrfToken,
  type Schemas,
} from "@workspace/api-client"

import type { PlanStep } from "@/components/assistant/plan"
import type { Answer } from "@/components/assistant/question-card"
import type { ModelRef } from "@/components/assistant/use-models"
import i18n from "@/lib/i18n"

export type ChatMessage = Schemas["ChatMessage"]
export type ChatPart = Schemas["ChatPart"]
export type ChatStatus = "loading" | "ready" | "streaming"
/** What a chat has used so far, and the spend limit per chat (Settings → AI). */
export type ChatSpend = {
  usage: Schemas["ChatUsage"]
  limit: number | null
}

type Handlers = {
  /** The server named the chat (first message). */
  onTitle?: (title: string) => void
  /** A turn finished (saved), so lists can refresh. */
  onDone?: () => void
}

/** Splits an SSE byte stream into (event, data) pairs. */
async function* readEvents(
  body: ReadableStream<Uint8Array>
): AsyncGenerator<[string, unknown]> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })
    let end: number
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      let event = "message"
      const data: string[] = []
      for (const line of chunk.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7)
        else if (line.startsWith("data: ")) data.push(line.slice(6))
      }
      try {
        yield [event, JSON.parse(data.join("\n"))]
      } catch {
        // a malformed event is skipped, not fatal
      }
    }
  }
}

/** Applies one streamed event to the reply being built (the last message). */
function applyEvent(
  reply: ChatMessage,
  event: string,
  data: Record<string, unknown>
) {
  const parts = [...reply.parts]
  const last = parts.at(-1)
  if (event === "text" || event === "reasoning") {
    const type = event === "text" ? "text" : "reasoning"
    const delta = String(data.delta ?? "")
    if (last && last.type === type && !data.new) {
      parts[parts.length - 1] = { ...last, text: (last.text ?? "") + delta }
    } else {
      parts.push({ type, text: delta, destructive: false, draft: false })
    }
  } else if (event === "tool-call") {
    const i = toolIndex(parts, data.id)
    if (i >= 0) {
      // An approved action is announced again when it runs.
      parts[i] = { ...parts[i]!, state: "running" }
    } else {
      parts.push({
        type: "tool",
        tool_call_id: String(data.id),
        tool_name: String(data.name),
        args: data.args,
        state: "running",
        destructive: false,
        draft: false,
      })
    }
  } else if (event === "tool-result") {
    const i = toolIndex(parts, data.id)
    if (i >= 0) {
      const error = (data.error as string | null) ?? null
      parts[i] = {
        ...parts[i]!,
        result: (data.result as string | null) ?? null,
        error,
        state: data.denied ? "denied" : error ? "error" : "done",
      }
    }
  } else if (event === "approval") {
    for (const call of (data.calls ?? []) as ApprovalCall[]) {
      const i = toolIndex(parts, call.id)
      if (i >= 0) {
        parts[i] = {
          ...parts[i]!,
          state: "approval",
          summary: call.summary,
          destructive: call.destructive,
        }
      }
    }
  } else if (event === "question") {
    for (const id of (data.ids ?? []) as string[]) {
      const i = toolIndex(parts, id)
      if (i >= 0) parts[i] = { ...parts[i]!, state: "question" }
    }
  } else if (event === "draft") {
    // "Double-check answers": what was written so far is revised next, so fold it away.
    for (const [i, p] of parts.entries()) {
      if (p.type === "text") parts[i] = { ...p, draft: true }
    }
  } else if (event === "job") {
    const i = toolIndex(parts, data.id)
    if (i >= 0) parts[i] = { ...parts[i]!, job_id: String(data.job_id) }
  }
  return { ...reply, parts }
}

type ApprovalCall = {
  id: string
  summary: string | null
  destructive: boolean
}

function toolIndex(parts: ChatPart[], id: unknown) {
  return parts.findIndex((p) => p.type === "tool" && p.tool_call_id === id)
}

/** What the chat is waiting on: tool calls in the last reply still asking for approval,
 * or questions still waiting for an answer. */
export function waitingCalls(messages: ChatMessage[]): ChatPart[] {
  const last = messages.at(-1)
  if (!last || last.role !== "assistant") return []
  return last.parts.filter(
    (p) =>
      p.type === "tool" && (p.state === "approval" || p.state === "question")
  )
}

/**
 * One chat's messages, plus sending a message and reading the streamed reply.
 * Uses fetch and a stream reader rather than EventSource, since sending is a POST.
 */
export function useChatStream(
  conversationId: string | null,
  handlers: Handlers = {}
) {
  const [messages, setMessages] = React.useState<ChatMessage[]>([])
  const [status, setStatus] = React.useState<ChatStatus>("loading")
  const [error, setError] = React.useState<string | null>(null)
  const [spend, setSpend] = React.useState<ChatSpend | null>(null)
  const [plan, setPlan] = React.useState<PlanStep[]>([])
  const [naming, setNaming] = React.useState(false)
  const sending = React.useRef(false)
  const handlersRef = useLatest(handlers)

  /** Answers to what the chat waits on, kept until every card has one; then they're
   * sent together (a run resumes only with every call answered) and the reply goes on
   * in the same message. */
  const [decided, setDecided] = React.useState<Record<string, boolean>>({})
  const [answered, setAnswered] = React.useState<Record<string, Answer>>({})
  React.useEffect(() => {
    setDecided({})
    setAnswered({})
  }, [conversationId])

  const load = React.useCallback(async () => {
    if (!conversationId) {
      setMessages([])
      setSpend(null)
      setPlan([])
      setStatus("ready")
      return
    }
    const { data } = await api.GET(
      "/api/assistant/conversations/{conversation_id}",
      {
        params: { path: { conversation_id: conversationId } },
      }
    )
    if (data) {
      setMessages(data.messages)
      setSpend({ usage: data.usage, limit: data.spend_limit_usd })
      setPlan(data.plan)
      setNaming(data.naming ?? false)
      setStatus(data.running ? "streaming" : "ready")
    } else {
      setStatus("ready")
    }
  }, [conversationId])

  React.useEffect(() => {
    // A chat created by `send` already shows its streaming reply; don't reload over it.
    if (sending.current) return
    setStatus("loading")
    setError(null)
    void load()
  }, [load])

  // A reply that's still running elsewhere (another tab, a reload): poll until done.
  React.useEffect(() => {
    if (status !== "streaming" || sending.current) return
    const timer = window.setInterval(load, 2000)
    return () => window.clearInterval(timer)
  }, [status, load])

  // A title model names a new chat after its first reply, without blocking the chat:
  // check back until it's done.
  React.useEffect(() => {
    if (!naming || !conversationId) return
    const timer = window.setInterval(async () => {
      const { data } = await api.GET(
        "/api/assistant/conversations/{conversation_id}",
        { params: { path: { conversation_id: conversationId } } }
      )
      if (data?.naming) return
      setNaming(false)
      if (data) handlersRef.current.onTitle?.(data.title)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [naming, conversationId, handlersRef])

  /** POSTs to a streaming endpoint and applies its events to the last reply. */
  const run = React.useCallback(
    async (id: string, path: string, body: unknown): Promise<boolean> => {
      setError(null)
      sending.current = true
      setStatus("streaming")
      let ok = true
      try {
        const headers: Record<string, string> = {
          "Content-Type": "application/json",
        }
        const token = getCsrfToken()
        if (token) headers["X-CSRF-Token"] = token
        const res = await fetch(`/api/assistant/conversations/${id}/${path}`, {
          method: "POST",
          headers,
          body: JSON.stringify(body),
        })
        if (!res.ok || !res.body) {
          const data = await res.json().catch(() => null)
          throw new Error(errorMessage(data, `HTTP ${res.status}`))
        }
        for await (const [event, data] of readEvents(res.body)) {
          const d = (data ?? {}) as Record<string, unknown>
          if (event === "error") {
            ok = false
            setError(String(d.message ?? i18n.t("assistant:chat.failed")))
          } else if (event === "title") {
            handlersRef.current.onTitle?.(String(d.title))
          } else if (event === "usage") {
            const usage = d as Schemas["ChatUsage"]
            setSpend((s) => ({ usage, limit: s?.limit ?? null }))
          } else if (event === "plan") {
            setPlan((d.steps ?? []) as PlanStep[])
          } else if (event === "done") {
            break
          } else {
            setMessages((m) => {
              const last = m.at(-1)
              if (!last || last.role !== "assistant") return m
              return [...m.slice(0, -1), applyEvent(last, event, d)]
            })
          }
        }
      } catch (err) {
        ok = false
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        sending.current = false
      }
      // The saved history is the source of truth (ids, and a failed turn isn't kept).
      const { data } = await api.GET(
        "/api/assistant/conversations/{conversation_id}",
        {
          params: { path: { conversation_id: id } },
        }
      )
      if (data) {
        setMessages(data.messages)
        setSpend({ usage: data.usage, limit: data.spend_limit_usd })
        setPlan(data.plan)
        setNaming(data.naming ?? false)
      }
      setStatus("ready")
      handlersRef.current.onDone?.()
      return ok
    },
    [handlersRef]
  )

  const send = React.useCallback(
    async (
      text: string,
      model: ModelRef | null,
      /** For a chat created just now, before the `conversationId` prop catches up. */
      id: string | null = conversationId
    ): Promise<boolean> => {
      if (!id) return false
      setDecided({})
      setAnswered({})
      const userMsg: ChatMessage = {
        id: `local-${Date.now()}`,
        role: "user",
        parts: [{ type: "text", text, destructive: false, draft: false }],
      }
      const reply: ChatMessage = {
        id: `local-${Date.now()}-r`,
        role: "assistant",
        parts: [],
      }
      // A new message denies the waiting actions and skips the questions; show that
      // before the reply.
      setMessages((m) => [
        ...m.map((msg, i) =>
          i === m.length - 1
            ? {
                ...msg,
                parts: msg.parts.map((p) =>
                  p.state === "approval"
                    ? { ...p, state: "denied" as const }
                    : p.state === "question"
                      ? { ...p, state: "done" as const, result: null }
                      : p
                ),
              }
            : msg
        ),
        userMsg,
        reply,
      ])
      return run(id, "messages", { text, model })
    },
    [conversationId, run]
  )

  const submit = React.useCallback(
    (
      nextDecided: Record<string, boolean>,
      nextAnswered: Record<string, Answer>
    ) => {
      if (!conversationId || sending.current) return
      const waiting = waitingCalls(messages)
      setDecided(nextDecided)
      setAnswered(nextAnswered)
      const done = waiting.every((p) =>
        p.state === "approval"
          ? p.tool_call_id! in nextDecided
          : p.tool_call_id! in nextAnswered
      )
      if (!done) return
      setDecided({})
      setAnswered({})
      setMessages((m) => {
        const last = m.at(-1)
        if (!last) return m
        const parts = last.parts.map((p) =>
          p.state === "approval" && p.tool_call_id
            ? {
                ...p,
                state: nextDecided[p.tool_call_id]
                  ? ("running" as const)
                  : ("denied" as const),
              }
            : p.state === "question"
              ? { ...p, state: "running" as const }
              : p
        )
        return [...m.slice(0, -1), { ...last, parts }]
      })
      const decisions = waiting
        .filter((p) => p.state === "approval")
        .map((p) => ({
          id: p.tool_call_id!,
          approve: nextDecided[p.tool_call_id!]!,
        }))
      const answers = waiting
        .filter((p) => p.state === "question")
        .map((p) => nextAnswered[p.tool_call_id!]!)
      void run(conversationId, "approvals", { decisions, answers })
    },
    [conversationId, messages, run]
  )

  /** Approve or deny one waiting action. */
  const decide = React.useCallback(
    (callId: string, approve: boolean) =>
      submit({ ...decided, [callId]: approve }, answered),
    [submit, decided, answered]
  )

  /** Answer (or skip) one waiting question. */
  const answer = React.useCallback(
    (a: Answer) => submit(decided, { ...answered, [a.id]: a }),
    [submit, decided, answered]
  )

  const stop = React.useCallback(async () => {
    if (!conversationId) return
    await api.POST("/api/assistant/conversations/{conversation_id}/stop", {
      params: { path: { conversation_id: conversationId } },
    })
  }, [conversationId])

  return {
    messages,
    status,
    error,
    send,
    stop,
    setError,
    decide,
    decided,
    answer,
    answered,
    waiting: waitingCalls(messages),
    spend,
    plan,
  }
}
