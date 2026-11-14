"use client"

import Link from "next/link"
import { CircleDollarSignIcon } from "lucide-react"

import { InputGroupButton } from "@workspace/ui/components/input-group"
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@workspace/ui/components/popover"
import {
  Progress,
  ProgressLabel,
  ProgressValue,
} from "@workspace/ui/components/progress"
import { cn } from "@workspace/ui/lib/utils"

import type { ChatSpend } from "@/components/assistant/use-chat-stream"

/** $2.00, $0.40, or $0.0063 when two decimals would show nothing. */
export function formatUsd(amount: number): string {
  if (amount === 0) return "$0.00"
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    ...(amount < 0.01
      ? { maximumSignificantDigits: 2 }
      : { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  }).format(amount)
}

const tokens = new Intl.NumberFormat("en-US", { notation: "compact" })

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  )
}

/**
 * What the current chat has cost, in the prompt bar (the AI Elements "Context"
 * pattern, in a popover so it also opens on touch). Hidden until the chat has used
 * anything.
 */
export function SpendButton({ spend }: { spend: ChatSpend | null }) {
  if (!spend) return null
  const { usage, limit } = spend
  const total = usage.input_tokens + usage.output_tokens
  if (total === 0) return null
  const cost = usage.cost ?? null
  const reached = limit !== null && cost !== null && cost >= limit
  const label =
    cost !== null ? formatUsd(cost) : `${tokens.format(total)} tokens`

  return (
    <Popover>
      <PopoverTrigger
        render={
          <InputGroupButton
            variant="ghost"
            size="sm"
            className={cn(
              "text-muted-foreground tabular-nums",
              reached &&
                "text-destructive hover:text-destructive aria-expanded:text-destructive"
            )}
            aria-label={`This chat's usage: ${label}`}
          />
        }
      >
        <CircleDollarSignIcon />
        {label}
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="gap-3">
        <PopoverHeader>
          <PopoverTitle>This chat&apos;s usage</PopoverTitle>
          <PopoverDescription>
            {cost === null
              ? "This model's prices aren't known, so only tokens are counted."
              : "An estimate from the model's published prices."}
          </PopoverDescription>
        </PopoverHeader>
        {limit !== null && cost !== null ? (
          <Progress value={Math.min(100, (cost / limit) * 100)}>
            <ProgressLabel className="text-sm font-normal">
              {formatUsd(cost)} of {formatUsd(limit)}
            </ProgressLabel>
            <ProgressValue className="ml-auto text-sm text-muted-foreground" />
          </Progress>
        ) : (
          <Row
            label="Spent"
            value={cost !== null ? formatUsd(cost) : "Unknown"}
          />
        )}
        <div className="flex flex-col gap-1">
          <Row label="Input tokens" value={tokens.format(usage.input_tokens)} />
          <Row
            label="Output tokens"
            value={tokens.format(usage.output_tokens)}
          />
        </div>
        {reached ? (
          <p className="text-destructive">
            This chat reached its spend limit. Start a new chat, or raise the
            limit in{" "}
            <Link href="/settings/ai/" className="underline">
              Settings → AI
            </Link>
            .
          </p>
        ) : limit !== null && cost === null ? (
          <p className="text-muted-foreground">
            The spend limit ({formatUsd(limit)}) can&apos;t apply to this model.
          </p>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}
