"use client"

import * as React from "react"
import { FolderIcon, PlusIcon } from "lucide-react"

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
        <h2 className="text-sm font-semibold">Destinations</h2>
        <Button size="sm" onClick={onAdd}>
          <PlusIcon data-icon="inline-start" />
          Add
        </Button>
      </div>
      {destinations.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FolderIcon />
            </EmptyMedia>
            <EmptyTitle>No destinations yet</EmptyTitle>
            <EmptyDescription>
              A destination is a folder or an rclone remote where backups are
              kept. Add one to start backing up.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead className="text-left">Location</TableHead>
              <TableHead className="text-right">Created</TableHead>
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
