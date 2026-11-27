"use client"

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"
import { ArrowLeftIcon, FileIcon, FolderIcon, Share2Icon } from "lucide-react"

import { api } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import { Skeleton } from "@workspace/ui/components/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@workspace/ui/components/table"

import { folderHref, parentOf } from "@/components/files/file-utils"
import {
  LinkActions,
  LinkBadges,
  type ShareLink,
} from "@/components/files/share-links"

/** /files/shares: every share link, newest first. */
export function SharesView() {
  const { t } = useTranslation("files")
  const [links, setLinks] = React.useState<ShareLink[] | null>(null)

  const load = React.useCallback(async () => {
    const { data } = await api.GET("/api/shares")
    setLinks(data ?? [])
  }, [])
  React.useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          render={<Link href="/files/" />}
          nativeButton={false}
        >
          <ArrowLeftIcon />
          {t("sharesView.files")}
        </Button>
        <h2 className="font-heading text-lg font-medium">
          {t("sharesView.title")}
        </h2>
      </div>
      {links === null ? (
        <Skeleton className="h-40 w-full" />
      ) : links.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Share2Icon />
            </EmptyMedia>
            <EmptyTitle>{t("sharesView.emptyTitle")}</EmptyTitle>
            <EmptyDescription>
              {t("sharesView.emptyDescription")}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("sharesView.shared")}</TableHead>
                <TableHead className="hidden md:table-cell">
                  {t("sharesView.link")}
                </TableHead>
                <TableHead className="hidden text-right sm:table-cell">
                  {t("sharesView.used")}
                </TableHead>
                <TableHead className="w-0">
                  <span className="sr-only">{t("sharesView.actions")}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {links.map((link) => {
                const Icon = link.kind === "dir" ? FolderIcon : FileIcon
                const folder =
                  link.kind === "dir" ? link.path : parentOf(link.path)
                return (
                  <TableRow key={link.id}>
                    <TableCell className="max-w-0 min-w-40">
                      <Link
                        href={folderHref({ location: link.location }, folder)}
                        className="flex min-w-0 items-center gap-2 font-medium hover:underline"
                      >
                        <Icon className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{link.name}</span>
                      </Link>
                      <p className="truncate text-xs text-muted-foreground">
                        {link.location_name}
                        {link.path ? `/${link.path}` : ""}
                      </p>
                      <div className="mt-1.5 md:hidden">
                        <LinkBadges link={link} />
                      </div>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <LinkBadges link={link} />
                    </TableCell>
                    <TableCell className="hidden text-right text-muted-foreground tabular-nums sm:table-cell">
                      {link.mode === "upload"
                        ? t("sharesView.uploads", { count: link.uploads })
                        : t("sharesView.downloads", { count: link.downloads })}
                    </TableCell>
                    <TableCell>
                      <LinkActions link={link} onRemoved={() => void load()} />
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}
