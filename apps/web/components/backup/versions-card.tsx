"use client"

import * as React from "react"
import { DownloadIcon, RefreshCcwIcon, Trash2Icon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
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
import { formatBytes } from "@/lib/format"

import { useVersions } from "./use-backup"

type Version = Schemas["VersionOut"]

type VersionsCardProps = {
  destinationId?: string | null
  item?: string
  onRestore?: (version: Version) => void
  onViewFiles?: (version: Version) => void
}

/** The versions (restic snapshots) of one item or of everything. */
export function VersionsCard({
  destinationId,
  item,
  onRestore,
  onViewFiles,
}: VersionsCardProps) {
  const { t } = useTranslation("backup")
  const { versions, error, load } = useVersions(destinationId, item)

  if (!versions) {
    return (
      <div className="flex min-w-0 flex-col gap-4 md:gap-6">
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  return (
    <div className="flex min-w-0 flex-col gap-4 md:gap-6">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{t("versions.title")}</h2>
        <Button
          size="sm"
          aria-label={t("versions.refresh")}
          onClick={() => void load()}
        >
          <RefreshCcwIcon data-icon="inline-start" />
        </Button>
      </div>
      {versions.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>{t("versions.empty.title")}</EmptyTitle>
            <EmptyDescription>
              {t("versions.empty.description")}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("versions.time")}</TableHead>
              <TableHead className="text-right">{t("versions.size")}</TableHead>
              <TableHead className="text-right">{t("versions.new")}</TableHead>
              <TableHead className="text-right">{t("versions.added")}</TableHead>
              <TableHead className="text-right">{t("versions.changed")}</TableHead>
              <TableHead className="text-right">{t("versions.removed")}</TableHead>
              <TableHead className="text-right">{t("versions.os")}</TableHead>
              <TableHead className="text-right" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {versions.map((v) => (
              <TableRow key={v.id}>
                <TableCell>{formatServerTime(v.time)}</TableCell>
                <TableCell className="text-right">
                  {formatBytes(v.size)}
                </TableCell>
                <TableCell className="text-right">
                  {formatBytes(v.new_bytes)}
                </TableCell>
                <TableCell className="text-right">
                  {v.files_added ?? "—"}
                </TableCell>
                <TableCell className="text-right">
                  {v.files_changed ?? "—"}
                </TableCell>
                <TableCell className="text-right">
                  {v.files_removed ?? "—"}
                </TableCell>
                <TableCell className="text-right">{v.os ?? "—"}</TableCell>
                <TableCell className="text-right">
                  <div className="flex items-center gap-2">
                    {onViewFiles && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onViewFiles(v)}
                        title={t("versions.viewFiles")}
                      >
                        <DownloadIcon data-icon="inline-start" />
                      </Button>
                    )}
                    {onRestore && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onRestore(v)}
                        title={t("versions.restore")}
                      >
                        <Trash2Icon data-icon="inline-start" />
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}
