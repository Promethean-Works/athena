"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import { PlusIcon, RefreshCwIcon, Trash2Icon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
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
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemTitle,
} from "@workspace/ui/components/item"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@workspace/ui/components/select"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { toast } from "@workspace/ui/components/toast"

import { JobDialog } from "@/components/job-dialog"
import { currentLocale } from "@/lib/i18n"

type CatalogOut = Schemas["CatalogOut"]
type Job = Schemas["JobOut"]
type Kind = "auto" | "athena"

function when(iso: string | null | undefined, never: string) {
  return iso ? new Date(iso).toLocaleString(currentLocale()) : never
}

export function CatalogsManager() {
  const { t } = useTranslation("store")
  const KINDS: { label: string; value: Kind }[] = [
    { label: t("catalogs.kindAuto"), value: "auto" },
    { label: t("catalogs.kindAthena"), value: "athena" },
  ]
  const [catalogs, setCatalogs] = React.useState<CatalogOut[] | null>(null)
  const [job, setJob] = React.useState<Job | null>(null)
  const [removing, setRemoving] = React.useState<CatalogOut | null>(null)
  const [name, setName] = React.useState("")
  const [url, setUrl] = React.useState("")
  const [kind, setKind] = React.useState<Kind>("auto")

  const load = React.useCallback(async () => {
    const { data } = await api.GET("/api/store/catalogs")
    if (data) setCatalogs(data)
  }, [])
  React.useEffect(() => void load(), [load])

  async function add(body: { name: string; url: string; kind: Kind }) {
    const { data, error } = await api.POST("/api/store/catalogs", { body })
    if (data) {
      setJob(data)
      setName("")
      setUrl("")
      void load()
    } else {
      toast.add({
        type: "error",
        title: t("catalogs.addFailed"),
        description: errorMessage(error),
      })
    }
  }

  async function refresh(c: CatalogOut) {
    const { data, error } = await api.POST(
      "/api/store/catalogs/{catalog_id}/refresh",
      { params: { path: { catalog_id: c.id } } }
    )
    if (data) setJob(data)
    else
      toast.add({
        type: "error",
        title: t("catalogs.refreshFailed", { name: c.name }),
        description: errorMessage(error),
      })
  }

  async function remove(c: CatalogOut) {
    setRemoving(null)
    const { error } = await api.DELETE("/api/store/catalogs/{catalog_id}", {
      params: { path: { catalog_id: c.id } },
    })
    if (error)
      toast.add({
        type: "error",
        title: t("catalogs.removeFailed", { name: c.name }),
        description: errorMessage(error),
      })
    else toast.add({ type: "success", title: t("catalogs.removed", { name: c.name }) })
    void load()
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_minmax(0,26rem)]">
      <div className="flex flex-col gap-4">
        {!catalogs ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <ItemGroup className="gap-2">
            {catalogs.map((c) => (
              <Item key={c.id} variant="outline">
                <ItemContent>
                  <ItemTitle>
                    {c.name}
                    {c.builtin ? (
                      <Badge variant="secondary">{t("catalogs.builtIn")}</Badge>
                    ) : null}
                    {c.error ? (
                      <Badge variant="destructive">{t("catalogs.refreshFailedBadge")}</Badge>
                    ) : null}
                  </ItemTitle>
                  <ItemDescription>
                    {c.builtin
                      ? t("catalogs.summaryBuiltin", { count: c.app_count })
                      : t("catalogs.summaryUpdated", {
                          count: c.app_count,
                          when: when(c.refreshed_at, t("catalogs.never")),
                        })}
                  </ItemDescription>
                  {c.url ? (
                    <ItemDescription className="font-mono text-xs break-all">
                      {c.url}
                    </ItemDescription>
                  ) : null}
                  {c.error ? (
                    <ItemDescription className="text-destructive">
                      {c.error}
                    </ItemDescription>
                  ) : null}
                </ItemContent>
                {!c.builtin ? (
                  <ItemActions>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => refresh(c)}
                    >
                      <RefreshCwIcon data-icon="inline-start" />
                      {t("catalogs.refresh")}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setRemoving(c)}
                    >
                      <Trash2Icon />
                      <span className="sr-only">
                        {t("catalogs.removeLabel", { name: c.name })}
                      </span>
                    </Button>
                  </ItemActions>
                ) : null}
              </Item>
            ))}
          </ItemGroup>
        )}
      </div>

      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>{t("catalogs.addTitle")}</CardTitle>
            <CardDescription>
              {t("catalogs.addDescription")}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void add({ name, url, kind })
              }}
            >
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="catalog-name">{t("catalogs.name")}</FieldLabel>
                  <Input
                    id="catalog-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("catalogs.namePlaceholder")}
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="catalog-url">URL</FieldLabel>
                  <Input
                    id="catalog-url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://github.com/you/athena-apps"
                    type="url"
                    required
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="catalog-kind">{t("catalogs.format")}</FieldLabel>
                  <Select
                    items={KINDS}
                    value={kind}
                    onValueChange={(v) => setKind((v as Kind) ?? "auto")}
                  >
                    <SelectTrigger id="catalog-kind">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectGroup>
                        {KINDS.map((k) => (
                          <SelectItem key={k.value} value={k.value}>
                            {k.label}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </SelectContent>
                  </Select>
                  <FieldDescription>
                    {t("catalogs.formatHint")}
                  </FieldDescription>
                </Field>
                <Field>
                  <Button type="submit" disabled={!name.trim() || !url.trim()}>
                    <PlusIcon data-icon="inline-start" />
                    {t("catalogs.add")}
                  </Button>
                </Field>
              </FieldGroup>
            </form>
          </CardContent>
        </Card>
      </div>

      <JobDialog
        job={job}
        onClose={() => setJob(null)}
        onFinished={() => void load()}
      />
      <AlertDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("catalogs.removeTitle", { name: removing?.name })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("catalogs.removeDescription")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("catalogs.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => removing && remove(removing)}
            >
              {t("catalogs.remove")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
