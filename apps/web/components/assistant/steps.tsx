"use client"

import * as React from "react"
import type { TFunction } from "i18next"
import { useTranslation } from "react-i18next"
import {
  BanIcon,
  CircleCheckIcon,
  FilePenLineIcon,
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
import { Markdown } from "@/components/assistant/markdown"
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

type ToolKey = keyof typeof import("@/locales/en/assistant.json")["steps"]["tools"]

/** What each tool is called in the trace (keys under `steps.tools`). */
const TOOL_KEYS: Record<string, ToolKey> = {
  get_capabilities: "getCapabilities",
  get_system_stats: "getSystemStats",
  list_apps: "listApps",
  app_logs: "appLogs",
  list_file_locations: "listFileLocations",
  list_files: "listFiles",
  read_text_file: "readFile",
  read_file: "readFile",
  write_file: "writeFile",
  edit_file: "editFile",
  list_directory: "listDirectory",
  create_directory: "createDirectory",
  search_store: "searchStore",
  read_tool_result: "readToolResult",
  ask_user_question: "askUserQuestion",
  advisor: "advisor",
  run_workflow: "runWorkflow",
  get_store_app: "getStoreApp",
  list_package_managers: "listPackageManagers",
  search_packages: "searchPackages",
  list_upgradable_packages: "listUpgradablePackages",
}

function toolTitle(
  part: ChatPart,
  running: boolean,
  t: TFunction<"assistant">
): string {
  const name = part.tool_name ?? "tool"
  // Actions that needed approval are titled by what they do.
  if (part.summary) return part.summary
  if (name === "ask_user_question" && !running) return answerSummary(part)
  if (name === "delegate_task") return delegateTitle(part, running, t)
  const key = TOOL_KEYS[name]
  const args = part.args as Record<string, unknown> | null
  if (!key) return t(running ? "steps.running" : "steps.ran", { name })
  const title = t(running ? `steps.tools.${key}.running` : `steps.tools.${key}.done`)
  return typeof args?.name === "string"
    ? t("steps.withSubject", { title, subject: args.name })
    : title
}

/** A delegation is titled by its task, cut to one line. */
function delegateTitle(
  part: ChatPart,
  running: boolean,
  t: TFunction<"assistant">
): string {
  const args = part.args as Record<string, unknown> | null
  const task = typeof args?.task === "string" ? args.task.split("\n")[0]! : ""
  const short = task.length > 80 ? `${task.slice(0, 79)}…` : task
  if (short) {
    return t(running ? "steps.helperRunningTask" : "steps.helperDoneTask", {
      task: short,
    })
  }
  return t(running ? "steps.helperRunning" : "steps.helperDone")
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
  const { t } = useTranslation("assistant")
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
          <TraceTitle>{running ? t("steps.thinking") : t("steps.thought")}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="whitespace-pre-wrap">
        {text}
      </TraceCollapsibleContent>
    </TraceCollapsible>
  )
}

/** The script a `run_workflow` call ran, above its result. */
function WorkflowScript({ part }: { part: ChatPart }) {
  const code = (part.args as Record<string, unknown> | null)?.code
  if (part.tool_name !== "run_workflow" || typeof code !== "string") return null
  return (
    <CodeBlock size="sm" className="mb-2">
      <CodeBlockContent className="max-h-48">{code}</CodeBlockContent>
    </CodeBlock>
  )
}

/** An answer the assistant revised afterwards ("Double-check answers"). */
function DraftRow({ text }: { text: string }) {
  const { t } = useTranslation("assistant")
  return (
    <TraceCollapsible>
      <TraceCollapsibleTrigger>
        <TraceLine>
          <TraceIcon>
            <FilePenLineIcon />
          </TraceIcon>
          <TraceTitle>{t("steps.draft")}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <Markdown>{text}</Markdown>
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
  const { t } = useTranslation("assistant")
  const approvals = React.useContext(ApprovalContext)
  const id = part.tool_call_id ?? ""
  const answer = approvals?.decided[id]
  const title = part.summary ?? t("steps.run", { name: part.tool_name })
  return (
    <div
      role="group"
      aria-label={t("steps.approvalNeeded", { title })}
      className="flex w-full flex-col gap-3 rounded-lg border bg-card p-3 text-sm text-card-foreground"
    >
      <div className="flex items-start gap-2">
        <ShieldQuestionIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="flex min-w-0 flex-col gap-0.5">
          <p className="font-medium">{title}</p>
          <p className="text-muted-foreground">
            {t("steps.approvalIntro")}
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
            {t("steps.deny")}
          </Button>
          <Button
            variant={part.destructive ? "destructive" : "default"}
            size="sm"
            disabled={!approvals || approvals.busy}
            onClick={() => approvals?.decide(id, true)}
          >
            {t("steps.approve")}
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground">
          {answer ? t("steps.approvedGoOn") : t("steps.deniedGoOn")}
        </p>
      )}
    </div>
  )
}

type Job = Schemas["JobOut"]

/** Opens the live log of the job an approved action started. */
function JobLogButton({ jobId }: { jobId: string }) {
  const { t } = useTranslation("assistant")
  const [job, setJob] = React.useState<Job | null>(null)
  async function open() {
    const { data, error } = await api.GET("/api/jobs/{job_id}", {
      params: { path: { job_id: jobId } },
    })
    if (data) setJob(data)
    else
      toast.add({
        type: "error",
        title: t("steps.logGone"),
        description: errorMessage(error),
      })
  }
  return (
    <>
      <Button variant="ghost" size="xs" onClick={() => void open()}>
        <ScrollTextIcon />
        {t("steps.log")}
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
  const { t } = useTranslation("assistant")
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
          <TraceTitle>{toolTitle(part, running, t)}</TraceTitle>
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
        <TraceTitle>
          {t("steps.denied", { title: toolTitle(part, true, t) })}
        </TraceTitle>
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
              ? t("steps.failed", { title: toolTitle(part, true, t) })
              : toolTitle(part, false, t)}
          </TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <WorkflowScript part={part} />
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
        part.type === "text" ? (
          <DraftRow key={i} text={part.text ?? ""} />
        ) : part.type === "reasoning" ? (
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
