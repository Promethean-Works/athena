"use client"

import * as React from "react"
import {
  ClockIcon,
  CopyIcon,
  Trash2Icon,
  WebhookIcon,
  ZapIcon,
} from "lucide-react"

import { api, errorMessage } from "@workspace/api-client"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@workspace/ui/components/alert-dialog"
import { Badge } from "@workspace/ui/components/badge"
import { Button } from "@workspace/ui/components/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@workspace/ui/components/item"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Switch } from "@workspace/ui/components/switch"
import { toast } from "@workspace/ui/components/toast"

import { checkCron } from "@/components/automation/cron"
import { NewTriggerDialog } from "@/components/automation/new-trigger-dialog"
import {
  actionSummary,
  formatServerTime,
  webhookUrl,
  type Trigger,
} from "@/components/automation/triggers"
import { copyText } from "@/lib/clipboard"

/** The trigger list with enable switches, webhook copy and delete. */
export function TriggersCard({
  triggers,
  error,
  load,
}: {
  triggers: Trigger[] | null
  error: string | null
  load: () => Promise<void>
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ZapIcon className="size-4 text-muted-foreground" /> Triggers
        </CardTitle>
        <CardDescription>
          Run an app or package action on a schedule or from a webhook.
        </CardDescription>
        <CardAction>
          <NewTriggerDialog onCreated={load} />
        </CardAction>
      </CardHeader>
      <CardContent>
        {triggers === null && error === null ? (
          <Skeleton className="h-32 w-full" />
        ) : triggers === null ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : triggers.length === 0 ? (
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ZapIcon />
              </EmptyMedia>
              <EmptyTitle>No triggers yet</EmptyTitle>
              <EmptyDescription>
                A trigger runs an action on a schedule (cron) or when its
                webhook is called, for example from n8n.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ItemGroup className="gap-2">
            {triggers.map((t) => (
              <TriggerRow key={t.id} trigger={t} onChange={load} />
            ))}
          </ItemGroup>
        )}
      </CardContent>
    </Card>
  )
}

function schedule(trigger: Trigger): string {
  if (trigger.kind !== "cron") return "When its webhook is called"
  if (!trigger.cron_expression) return "No schedule"
  const check = checkCron(trigger.cron_expression)
  return check.ok ? check.description : trigger.cron_expression
}

function TriggerRow({
  trigger,
  onChange,
}: {
  trigger: Trigger
  onChange: () => Promise<void>
}) {
  const isWebhook = trigger.kind === "http"
  return (
    <Item variant="outline" size="sm" role="listitem">
      <ItemContent className="min-w-0 basis-48">
        <ItemTitle className="w-full min-w-0">
          <span className="truncate">{trigger.name}</span>
          <Badge variant="outline" className="shrink-0">
            {isWebhook ? <WebhookIcon /> : <ClockIcon />}
            {isWebhook ? "Webhook" : "Cron"}
          </Badge>
        </ItemTitle>
        <ItemDescription className="break-words">
          {actionSummary(trigger.action)} · {schedule(trigger)}
          {trigger.kind === "cron" && trigger.cron_expression ? (
            <span className="font-mono text-xs">
              {" "}
              ({trigger.cron_expression})
            </span>
          ) : null}
        </ItemDescription>
        {trigger.kind === "cron" && trigger.enabled && trigger.next_run_at ? (
          <ItemDescription className="text-xs">
            Next run {formatServerTime(trigger.next_run_at)}
          </ItemDescription>
        ) : null}
      </ItemContent>
      <ItemActions className="ml-auto">
        <EnabledSwitch trigger={trigger} onChange={onChange} />
        {isWebhook && trigger.webhook_token ? (
          <CopyWebhookButton token={trigger.webhook_token} />
        ) : null}
        <DeleteTriggerButton trigger={trigger} onDeleted={onChange} />
      </ItemActions>
    </Item>
  )
}

function EnabledSwitch({
  trigger,
  onChange,
}: {
  trigger: Trigger
  onChange: () => Promise<void>
}) {
  const [saving, setSaving] = React.useState(false)

  async function toggle(enabled: boolean) {
    setSaving(true)
    const { error } = await api.PATCH("/api/automation/triggers/{trigger_id}", {
      params: { path: { trigger_id: trigger.id } },
      body: {
        kind: trigger.kind === "http" ? "http" : "cron",
        name: trigger.name,
        cron_expression: trigger.cron_expression,
        action: trigger.action,
        enabled,
      },
    })
    await onChange()
    setSaving(false)
    if (error) {
      toast.add({
        type: "error",
        title: "Couldn't change the trigger",
        description: errorMessage(error),
      })
    } else {
      toast.add({
        type: "success",
        title: `${trigger.name} ${enabled ? "enabled" : "paused"}`,
      })
    }
  }

  return (
    <Switch
      checked={trigger.enabled}
      onCheckedChange={toggle}
      disabled={saving}
      aria-label={`${trigger.name} enabled`}
    />
  )
}

function CopyWebhookButton({ token }: { token: string }) {
  return (
    <Button
      size="icon-sm"
      variant="ghost"
      aria-label="Copy webhook URL"
      title="Copy webhook URL"
      onClick={async () => {
        const ok = await copyText(webhookUrl(token))
        toast.add(
          ok
            ? { type: "success", title: "Webhook URL copied" }
            : { type: "error", title: "Couldn't copy" }
        )
      }}
    >
      <CopyIcon />
    </Button>
  )
}

function DeleteTriggerButton({
  trigger,
  onDeleted,
}: {
  trigger: Trigger
  onDeleted: () => Promise<void>
}) {
  const [open, setOpen] = React.useState(false)
  const [deleting, setDeleting] = React.useState(false)

  async function remove() {
    setDeleting(true)
    const { error } = await api.DELETE(
      "/api/automation/triggers/{trigger_id}",
      {
        params: { path: { trigger_id: trigger.id } },
      }
    )
    await onDeleted()
    setDeleting(false)
    if (error) {
      toast.add({
        type: "error",
        title: "Couldn't delete the trigger",
        description: errorMessage(error),
      })
      return
    }
    setOpen(false)
    toast.add({ type: "success", title: "Trigger deleted" })
  }

  return (
    <>
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label={`Delete ${trigger.name}`}
        title="Delete"
        onClick={() => setOpen(true)}
      >
        <Trash2Icon />
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {trigger.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              It stops running
              {trigger.kind === "http"
                ? " and its webhook URL stops working"
                : ""}
              . Past job runs stay in the log.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={remove}
              disabled={deleting}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
