"use client"

import * as React from "react"
import { MessageCircleQuestionIcon } from "lucide-react"

import type { Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import { Checkbox } from "@workspace/ui/components/checkbox"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
  FieldLegend,
  FieldSet,
  FieldTitle,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  RadioGroup,
  RadioGroupItem,
} from "@workspace/ui/components/radio-group"

import type { ChatPart } from "@/components/assistant/use-chat-stream"

export type Answer = Schemas["Answer"]

/** What the model sends to `ask_user_question` (the harness's schema). */
type Question = {
  header: string
  question: string
  options: { label: string; description?: string | null }[]
  multi_select?: boolean
}

/** The server cuts typed answers to this (`questions.MAX_CUSTOM`). */
const MAX_CUSTOM = 500

type Pick = { selected: string[]; custom: string }

export function questionsOf(part: ChatPart): Question[] {
  const args = part.args as { questions?: Question[] } | null
  return Array.isArray(args?.questions) ? args.questions : []
}

function OneQuestion({
  q,
  index,
  pick,
  onChange,
  disabled,
}: {
  q: Question
  index: number
  pick: Pick
  onChange: (p: Pick) => void
  disabled: boolean
}) {
  const base = `${React.useId()}-q${index}`
  return (
    <FieldSet disabled={disabled}>
      <FieldLegend variant="label">{q.header}</FieldLegend>
      <FieldDescription className="whitespace-pre-wrap text-foreground">
        {q.question}
      </FieldDescription>
      {q.multi_select ? (
        <div className="grid gap-2">
          {q.options.map((o, i) => (
            <FieldLabel key={o.label} htmlFor={`${base}-${i}`}>
              <Field orientation="horizontal">
                <Checkbox
                  id={`${base}-${i}`}
                  checked={pick.selected.includes(o.label)}
                  onCheckedChange={(c) =>
                    onChange({
                      custom: "",
                      selected: c
                        ? [...pick.selected, o.label]
                        : pick.selected.filter((s) => s !== o.label),
                    })
                  }
                />
                <OptionText label={o.label} description={o.description} />
              </Field>
            </FieldLabel>
          ))}
        </div>
      ) : (
        <RadioGroup
          value={pick.selected[0] ?? null}
          onValueChange={(v) => onChange({ custom: "", selected: [String(v)] })}
        >
          {q.options.map((o, i) => (
            <FieldLabel key={o.label} htmlFor={`${base}-${i}`}>
              <Field orientation="horizontal">
                <RadioGroupItem id={`${base}-${i}`} value={o.label} />
                <OptionText label={o.label} description={o.description} />
              </Field>
            </FieldLabel>
          ))}
        </RadioGroup>
      )}
      <Input
        aria-label={`Your own answer to ${q.header}`}
        placeholder="Or type your own answer"
        maxLength={MAX_CUSTOM}
        value={pick.custom}
        onChange={(e) => onChange({ selected: [], custom: e.target.value })}
      />
    </FieldSet>
  )
}

function OptionText({
  label,
  description,
}: {
  label: string
  description?: string | null
}) {
  return (
    <FieldContent>
      <FieldTitle>{label}</FieldTitle>
      {description ? <FieldDescription>{description}</FieldDescription> : null}
    </FieldContent>
  )
}

/** Multiple-choice questions from the assistant (`ask_user_question`): pick an option per
 * question, or type an answer, or skip them all. The model wrote these, so the card says
 * so and never asks for secrets. */
export function QuestionCard({
  part,
  answered,
  busy,
  onAnswer,
}: {
  part: ChatPart
  /** Already answered here, waiting for the actions next to it. */
  answered: Answer | undefined
  busy: boolean
  onAnswer: (answer: Answer) => void
}) {
  const questions = questionsOf(part)
  const [picks, setPicks] = React.useState<Pick[]>(() =>
    questions.map(() => ({ selected: [], custom: "" }))
  )
  const ready = picks.every((p) => p.selected.length > 0 || p.custom.trim())
  const id = part.tool_call_id ?? ""
  const title = questions.length === 1 ? questions[0]!.header : "Questions"

  function send(declined: boolean) {
    onAnswer({
      id,
      declined,
      answers: declined
        ? []
        : questions.map((q, i) => {
            const p = picks[i]!
            return p.custom.trim()
              ? { header: q.header, custom: p.custom.trim(), selected: [] }
              : { header: q.header, selected: p.selected }
          }),
    })
  }

  return (
    <div
      role="group"
      aria-label={`The assistant asks: ${title}`}
      className="flex w-full flex-col gap-4 rounded-lg border bg-card p-3 text-sm text-card-foreground"
    >
      <div className="flex items-start gap-2">
        <MessageCircleQuestionIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <p className="text-muted-foreground">
          The assistant is asking before it goes on. Never answer with a
          password or key.
        </p>
      </div>
      {questions.map((q, i) => (
        <OneQuestion
          key={q.header}
          q={q}
          index={i}
          pick={picks[i]!}
          disabled={answered !== undefined}
          onChange={(p) =>
            setPicks((all) => all.map((old, j) => (j === i ? p : old)))
          }
        />
      ))}
      {answered === undefined ? (
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => send(true)}
          >
            Skip
          </Button>
          <Button
            size="sm"
            disabled={busy || !ready}
            onClick={() => send(false)}
          >
            Send answers
          </Button>
        </div>
      ) : (
        <p className="text-muted-foreground">
          {answered.declined ? "Skipped" : "Answered"}. Answer the other cards
          to go on.
        </p>
      )}
    </div>
  )
}

/** One line for an answered question: what the admin picked, from the tool's result. */
export function answerSummary(part: ChatPart): string {
  try {
    const result = JSON.parse(part.result ?? "") as Record<string, string[]>
    return (
      "You answered: " +
      Object.values(result)
        .map((v) => v.join(", "))
        .join("; ")
    )
  } catch {
    return "You skipped the question"
  }
}
