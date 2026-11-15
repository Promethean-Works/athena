"use client"

import * as React from "react"
import {
  BanIcon,
  CircleCheckIcon,
  LoaderCircleIcon,
  ScrollTextIcon,
  ShieldQuestionIcon,
  WrenchIcon,
} from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  CodeBlock,
  CodeBlockContent,
} from "@workspace/ui/components/code-block"
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@workspace/ui/components/trace"
import { toast } from "@workspace/ui/components/toast"

import {
  answerSummary,
  QuestionCard,
  type Answer,
} from "@/components/assistant/question-card"
import type { ChatPart } from "@/components/assistant/use-chat-stream"
import { JobDialog } from "@/components/job-dialog"

type Approvals = {
  decide: (callId: string, approve: boolean) => void
  decided: Record<string, boolean>
  answer: (answer: Answer) => void
  answered: Record<string, Answer>
  /** A reply is streaming, so answers wait. */
  busy: boolean
}

const ApprovalContext = React.createContext<Approvals | null>(null)

/** Gives the approval and question cards in a chat their handlers. */
export function ApprovalProvider({
  value,
  children,
}: {
  value: Approvals
  children: React.ReactNode
}) {
  return <ApprovalContext value={value}>{children}</ApprovalContext>
}

/** What each tool is called in the trace. */
const TOOL_TITLES: Record<string, [running: string, done: string]> = {
  get_capabilities: [
    "Checking what this server can do",
    "Checked what this server can do",
  ],
  get_system_stats: ["Reading system stats", "Read system stats"],
  list_apps: ["Listing apps", "Listed apps"],
  app_logs: ["Reading app logs", "Read app logs"],
  list_file_locations: ["Listing file locations", "Listed file locations"],
  list_files: ["Listing files", "Listed files"],
  read_text_file: ["Reading a file", "Read a file"],
  search_store: ["Searching the app store", "Searched the app store"],
  read_tool_result: ["Reading a saved tool result", "Read a saved tool result"],
  ask_user_question: ["Waiting for your answer", "Asked you"],
  get_store_app: ["Reading a store app", "Read a store app"],
  list_package_managers: [
    "Listing package managers",
    "Listed package managers",
  ],
  search_packages: ["Searching packages", "Searched packages"],
  list_upgradable_packages: [
    "Checking for package updates",
    "Checked for package updates",
  ],
}

function toolTitle(part: ChatPart, running: boolean): string {
  const name = part.tool_name ?? "tool"
  // Actions that needed approval are titled by what they do.
  if (part.summary) return part.summary
  if (name === "ask_user_question" && !running) return answerSummary(part)
  const titles = TOOL_TITLES[name]
  const args = part.args as Record<string, unknown> | null
  const subject = typeof args?.name === "string" ? ` of ${args.name}` : ""
  if (!titles) return running ? `Running ${name}` : `Ran ${name}`
  return (running ? titles[0] : titles[1]) + subject
}

function pretty(text: string | null | undefined): string {
  if (!text) return ""
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}

function ReasoningRow({ text, running }: { text: string; running: boolean }) {
  const [open, setOpen] = React.useState<boolean>()
  return (
    <TraceCollapsible open={open ?? running} onOpenChange={setOpen}>
      <TraceCollapsibleTrigger>
        <TraceLine status={running ? "running" : undefined}>
          <TraceIcon>
            {running ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <CircleCheckIcon />
            )}
          </TraceIcon>
          <TraceTitle>{running ? "Thinking" : "Thought"}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="whitespace-pre-wrap">
        {text}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  )
}

/** An action's arguments: short values inline, long text (a compose file) as code. */
function Args({ args }: { args: unknown }) {
  const entries = Object.entries((args ?? {}) as Record<string, unknown>)
  if (entries.length === 0) return null
  return (
    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
      {entries.map(([key, value]) =>
        typeof value === "string" && value.includes("\n") ? (
          <React.Fragment key={key}>
            <dt className="text-muted-foreground">{key}</dt>
            <dd className="min-w-0">
              <CodeBlock size="sm">
                <CodeBlockContent className="max-h-48">
                  {value}
                </CodeBlockContent>
              </CodeBlock>
            </dd>
          </React.Fragment>
        ) : (
          <React.Fragment key={key}>
            <dt className="text-muted-foreground">{key}</dt>
            <dd className="min-w-0 font-mono break-all">
              {typeof value === "string" ? value : JSON.stringify(value)}
            </dd>
          </React.Fragment>
        )
      )}
    </dl>
  )
}

/** The Confirmation pattern from AI Elements: what the assistant wants to do, and
 * Approve/Deny. Nothing runs until the admin approves. */
function ApprovalCard({ part }: { part: ChatPart }) {
  const approvals = React.useContext(ApprovalContext)
  const id = part.tool_call_id ?? ""
  const answer = approvals?.decided[id]
  const title = part.summary ?? `Run ${part.tool_name}`
  return (
    <div
      role="group"
      aria-label={`Approval needed: ${title}`}
      className="flex w-full flex-col gap-3 rounded-lg border bg-card p-3 text-sm text-card-foreground"
    >
      <div className="flex items-start gap-2">
        <ShieldQuestionIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="font-medium">{title}</p>
          <p className="text-muted-foreground">
            The assistant wants to do this. Nothing happens until you approve.
          </p>
        </div>
      </div>
      <Args args={part.args} />
      {answer === undefined ? (
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!approvals || approvals.busy}
            onClick={() => approvals?.decide(id, false)}
          >
            Deny
          </Button>
          <Button
            variant={part.destructive ? "destructive" : "default"}
            size="sm"
            disabled={!approvals || approvals.busy}
            onClick={() => approvals?.decide(id, true)}
          >
            Approve
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground">
          {answer ? "Approved" : "Denied"}. Answer the other cards to go on.
        </p>
      )}
    </div>
  )
}

type Job = Schemas["JobOut"]

/** Opens the live log of the job an approved action started. */
function JobLogButton({ jobId }: { jobId: string }) {
  const [job, setJob] = React.useState<Job | null>(null)
  async function open() {
    const { data, error } = await api.GET("/api/jobs/{job_id}", {
      params: { path: { job_id: jobId } },
    })
    if (data) setJob(data)
    else
      toast.add({
        type: "error",
        title: "That log is gone",
        description: errorMessage(error),
      })
  }
  return (
    <>
      <Button variant="ghost" size="xs" onClick={() => void open()}>
        <ScrollTextIcon />
        Log
      </Button>
      <JobDialog job={job} onClose={() => setJob(null)} />
    </>
  )
}

function WaitingQuestion({ part }: { part: ChatPart }) {
  const approvals = React.useContext(ApprovalContext)
  return (
    <QuestionCard
      part={part}
      answered={approvals?.answered[part.tool_call_id ?? ""]}
      busy={!approvals || approvals.busy}
      onAnswer={(a) => approvals?.answer(a)}
    />
  )
}

function ToolRow({ part, streaming }: { part: ChatPart; streaming: boolean }) {
  const running = part.state === "running" && streaming
  if (part.state === "approval") return <ApprovalCard part={part} />
  if (part.state === "question") return <WaitingQuestion part={part} />
  if (running || part.state === "running") {
    // Still running, or the reply stopped before the tool answered.
    return (
      <div className="flex items-center gap-1">
        <TraceLine status={running ? "running" : "pending"}>
          <TraceIcon>
            {running ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <WrenchIcon />
            )}
          </TraceIcon>
          <TraceTitle>{toolTitle(part, running)}</TraceTitle>
        </TraceLine>
        {part.job_id ? <JobLogButton jobId={part.job_id} /> : null}
      </div>
    )
  }
  if (part.state === "denied") {
    return (
      <TraceLine status="pending">
        <TraceIcon>
          <BanIcon />
        </TraceIcon>
        <TraceTitle>Denied: {toolTitle(part, true)}</TraceTitle>
      </TraceLine>
    )
  }
  const failed = part.state === "error"
  const row = (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>
        <TraceLine status={failed ? "error" : undefined}>
          <TraceIcon>
            <WrenchIcon />
          </TraceIcon>
          <TraceTitle>
            {failed
              ? `Failed: ${toolTitle(part, true)}`
              : toolTitle(part, false)}
          </TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <CodeBlock size="sm" variant={failed ? "destructive" : "default"}>
          <CodeBlockContent wrap className="max-h-64">
            {pretty(failed ? (part.error ?? part.result) : part.result)}
          </CodeBlockContent>
        </CodeBlock>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  )
  if (!part.job_id) return row
  return (
    <div className="flex items-start gap-1">
      <div className="min-w-0 flex-1">{row}</div>
      <JobLogButton jobId={part.job_id} />
    </div>
  )
}

/** Tool calls shown elsewhere: `write_plan` is the checklist above the prompt bar. */
export function isShown(part: ChatPart): boolean {
  return part.tool_name !== "write_plan"
}

/** Reasoning and tool calls of a reply, as a shadcn Trace. */
export function Steps({
  parts,
  streaming,
}: {
  parts: ChatPart[]
  streaming: boolean
}) {
  if (parts.length === 0) return null
  return (
    <Trace>
      {parts.map((part, i) =>
        part.type === "reasoning" ? (
          <ReasoningRow
            key={i}
            text={part.text ?? ""}
            running={streaming && i === parts.length - 1}
          />
        ) : (
          <ToolRow
            key={part.tool_call_id ?? i}
            part={part}
            streaming={streaming}
          />
        )
      )}
    </Trace>
  )
}
