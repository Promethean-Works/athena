"use client"

import * as React from "react"
import { FolderIcon, PlusIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { Button } from "@workspace/ui/components/button"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"
import { formatServerTime } from "@/components/automation/triggers"

import { useDestinations } from "./use-backup"

/** The list of backup destinations (repositories). */
export function DestinationsCard({ onAdd }: { onAdd: () => void }) {
  const { t } = useTranslation("backup")
  const { destinations, error } = useDestinations()

  if (!destinations) {
    return (
      <div className="flex min-w-0 flex-col gap-4 md:gap-6">
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-4 md:gap-6">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{t("destinations.title")}</h2>
        <Button size="sm" onClick={onAdd}>
          <PlusIcon data-icon="inline-start" />
          {t("add")}
        </Button>
      </div>
      {destinations.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FolderIcon />
            </EmptyMedia>
            <EmptyTitle>{t("destinations.empty.title")}</EmptyTitle>
            <EmptyDescription>
              {t("destinations.empty.description")}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("destinations.name")}</TableHead>
              <TableHead>{t("destinations.kind")}</TableHead>
              <TableHead className="text-left">
                {t("destinations.location")}
              </TableHead>
              <TableHead className="text-right">
                {t("destinations.created")}
              </TableHead>
              <TableHead className="text-right" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {destinations.map((d) => (
              <TableRow key={d.id}>
                <TableCell>{d.name}</TableCell>
                <TableCell>{d.kind}</TableCell>
                <TableCell className="truncate text-left" title={d.location}>
                  {d.location}
                </TableCell>
                <TableCell className="text-right">
                  {formatServerTime(d.created_at)}
                </TableCell>
                <TableCell className="text-right" />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
