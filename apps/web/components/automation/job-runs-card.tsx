"use client"

import { HistoryIcon } from "lucide-react"

import { Badge } from "@workspace/ui/components/badge"
import {
  Card,
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
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@workspace/ui/components/item"
import { Skeleton } from "@workspace/ui/components/skeleton"

import {
  formatServerTime,
  useJobRuns,
  type JobRun,
  type Trigger,
} from "@/components/automation/triggers"

function badgeVariant(status: string): "secondary" | "destructive" | "outline" {
  if (status === "failed") return "destructive"
  if (status === "succeeded") return "secondary"
  return "outline"
}

/** The latest job runs, newest first, named after their trigger. */
export function JobRunsCard({ triggers }: { triggers: Trigger[] | null }) {
  const { runs, error } = useJobRuns()
  const names = new Map((triggers ?? []).map((t) => [t.id, t.name]))
  const nameOf = (run: JobRun) =>
    (run.trigger_id && names.get(run.trigger_id)) ||
    (triggers === null ? "Trigger" : "Deleted trigger")

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <HistoryIcon className="size-4 text-muted-foreground" /> Job runs
        </CardTitle>
        <CardDescription>
          The latest runs, refreshed every few seconds.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {runs === null && error === null ? (
          <Skeleton className="h-24 w-full" />
        ) : runs === null ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : runs.length === 0 ? (
          <Empty className="border">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <HistoryIcon />
              </EmptyMedia>
              <EmptyTitle>No job runs yet</EmptyTitle>
              <EmptyDescription>
                Runs show up here when a trigger fires.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ItemGroup className="gap-2">
            {runs.map((run) => (
              <Item key={run.id} variant="outline" size="xs" role="listitem">
                <ItemContent className="min-w-0">
                  <ItemTitle className="w-full min-w-0">
                    <span className="truncate">{nameOf(run)}</span>
                    <Badge
                      variant={badgeVariant(run.status)}
                      className="ml-auto shrink-0"
                    >
                      {run.status}
                    </Badge>
                  </ItemTitle>
                  <ItemDescription>
                    {formatServerTime(run.started_at)}
                  </ItemDescription>
                  {run.error ? (
                    <ItemDescription
                      className="break-words text-destructive"
                      title={run.error}
                    >
                      {run.error}
                    </ItemDescription>
                  ) : null}
                </ItemContent>
              </Item>
            ))}
          </ItemGroup>
        )}
        {runs !== null && error ? (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
