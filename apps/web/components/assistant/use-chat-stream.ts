"use client"

import * as React from "react"

import {
  api,
  errorMessage,
  getCsrfToken,
  type Schemas,
} from "@workspace/api-client"

import type { ModelRef } from "@/components/assistant/use-models"

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
      parts.push({ type, text: delta, destructive: false })
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

/** The actions the chat is waiting on: tool calls in the last reply still asking for approval. */
export function waitingCalls(messages: ChatMessage[]): ChatPart[] {
  const last = messages.at(-1)
  if (!last || last.role !== "assistant") return []
  return last.parts.filter((p) => p.type === "tool" && p.state === "approval")
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
  const sending = React.useRef(false)
  const handlersRef = React.useRef(handlers)
  handlersRef.current = handlers

  const load = React.useCallback(async () => {
    if (!conversationId) {
      setMessages([])
      setSpend(null)
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
            setError(String(d.message ?? "The assistant failed"))
          } else if (event === "title") {
            handlersRef.current.onTitle?.(String(d.title))
          } else if (event === "usage") {
            const usage = d as Schemas["ChatUsage"]
            setSpend((s) => ({ usage, limit: s?.limit ?? null }))
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
      }
      setStatus("ready")
      handlersRef.current.onDone?.()
      return ok
    },
    []
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
      const userMsg: ChatMessage = {
        id: `local-${Date.now()}`,
        role: "user",
        parts: [{ type: "text", text, destructive: false }],
      }
      const reply: ChatMessage = {
        id: `local-${Date.now()}-r`,
        role: "assistant",
        parts: [],
      }
      // A new message denies the waiting actions; show that before the reply.
      setMessages((m) => [
        ...m.map((msg, i) =>
          i === m.length - 1
            ? {
                ...msg,
                parts: msg.parts.map((p) =>
                  p.state === "approval"
                    ? { ...p, state: "denied" as const }
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

  /** Approve or deny one waiting action. Once every one has an answer, they're sent
   * together and the reply continues in the same message. */
  const [decided, setDecided] = React.useState<Record<string, boolean>>({})
  React.useEffect(() => setDecided({}), [conversationId])
  const decide = React.useCallback(
    (callId: string, approve: boolean) => {
      if (!conversationId || sending.current) return
      const waiting = waitingCalls(messages)
      const next = { ...decided, [callId]: approve }
      setDecided(next)
      if (!waiting.every((p) => p.tool_call_id! in next)) return
      setDecided({})
      setMessages((m) => {
        const last = m.at(-1)
        if (!last) return m
        const parts = last.parts.map((p) =>
          p.state === "approval" && p.tool_call_id
            ? {
                ...p,
                state: next[p.tool_call_id]
                  ? ("running" as const)
                  : ("denied" as const),
              }
            : p
        )
        return [...m.slice(0, -1), { ...last, parts }]
      })
      const decisions = waiting.map((p) => ({
        id: p.tool_call_id!,
        approve: next[p.tool_call_id!]!,
      }))
      void run(conversationId, "approvals", { decisions })
    },
    [conversationId, decided, messages, run]
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
    waiting: waitingCalls(messages),
    spend,
  }
}
