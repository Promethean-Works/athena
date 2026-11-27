"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleXIcon,
  PlusIcon,
} from "lucide-react"

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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { toast } from "@workspace/ui/components/toast"

import { JobDialog } from "@/components/job-dialog"
import { useCapabilities } from "@/components/capabilities-provider"
import { ManagerLogo } from "@/components/packages/package-icon"
import { usePasswordPrompt } from "@/components/packages/password-dialog"

type Installable = Schemas["InstallableOut"]
type Job = Schemas["JobOut"]

/**
 * "Add a package manager": the managers this OS supports that aren't installed yet,
 * each with what it needs. Installing downloads the vendor's official installer on
 * the server and runs it as a job; the new tab appears when detection finds it.
 */
export function AddManager({ onAdded }: { onAdded: () => void }) {
  const { t } = useTranslation("packages")
  const { refresh } = useCapabilities()
  const [open, setOpen] = React.useState(false)
  const [list, setList] = React.useState<Installable[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [confirm, setConfirm] = React.useState<Installable | null>(null)
  const [job, setJob] = React.useState<Job | null>(null)
  const { ask, dialog: passwordDialog } = usePasswordPrompt()

  const load = React.useCallback(async () => {
    setError(null)
    const { data, error: err } = await api.GET("/api/packages/installable")
    if (data) setList(data)
    else setError(errorMessage(err))
  }, [])

  // Load when the list is first opened, so the page itself stays quick.
  React.useEffect(() => {
    if (open && list === null && !error) void load()
  }, [open, list, error, load])

  async function install(item: Installable) {
    const password = item.needs_password ? await ask(item.label) : null
    if (item.needs_password && !password) return
    const { data, error: err } = await api.POST(
      "/api/packages/installable/{installer}/install",
      { params: { path: { installer: item.id } }, body: { password } }
    )
    if (data) {
      setJob(data)
      setOpen(false)
    } else {
      toast.add({
        type: "error",
        title: t("add.failed", { name: item.label }),
        description: errorMessage(err),
      })
    }
  }

  // The dialog stays closed while the job runs; the list is reloaded next time.
  async function finished() {
    setList(null)
    await refresh()
    onAdded()
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <PlusIcon data-icon="inline-start" />
        {t("add.button")}
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("add.title")}</DialogTitle>
            <DialogDescription>{t("add.description")}</DialogDescription>
          </DialogHeader>
          {error ? (
            <p className="font-mono text-xs break-all text-destructive">
              {error}
            </p>
          ) : list === null ? (
            <Skeleton className="h-32 w-full" />
          ) : list.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("add.none")}</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {list.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-col gap-2 rounded-lg border p-3"
                >
                  <div className="flex items-start gap-3">
                    <ManagerLogo
                      id={item.id}
                      label={item.label}
                      hasLogo
                      src={`/api/packages/installable/${item.id}/logo`}
                      className="size-8"
                    />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="font-medium">{item.label}</span>
                      <span className="text-sm text-muted-foreground">
                        {item.summary}
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">
                        {item.site}
                      </span>
                    </div>
                    <Button
                      size="sm"
                      disabled={!item.ready}
                      onClick={() => setConfirm(item)}
                    >
                      {t("add.install")}
                    </Button>
                  </div>
                  <ul className="flex flex-col gap-1 text-sm">
                    {item.requirements.map((r) => (
                      <li key={r.label} className="flex items-start gap-2">
                        {r.met ? (
                          <CircleCheckIcon className="mt-0.5 size-4 shrink-0 text-emerald-600" />
                        ) : (
                          <CircleXIcon className="mt-0.5 size-4 shrink-0 text-destructive" />
                        )}
                        <span>
                          {r.label}
                          {r.hint ? (
                            <span className="block text-muted-foreground">
                              {r.hint}
                            </span>
                          ) : null}
                        </span>
                      </li>
                    ))}
                    {item.needs_password ? (
                      <li className="flex items-start gap-2 text-muted-foreground">
                        <CircleAlertIcon className="mt-0.5 size-4 shrink-0" />
                        <span>{t("add.needsPassword")}</span>
                      </li>
                    ) : null}
                  </ul>
                </li>
              ))}
            </ul>
          )}
          {list && list.some((i) => !i.ready) ? (
            <Badge variant="outline" className="self-start">
              {t("add.unmetNote")}
            </Badge>
          ) : null}
        </DialogContent>
      </Dialog>

      <AlertDialog
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t("add.confirmTitle", { name: confirm?.label ?? "" })}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t("add.confirmDescription", { site: confirm?.site ?? "" })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const item = confirm
                setConfirm(null)
                if (item) void install(item)
              }}
            >
              {t("add.install")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {passwordDialog}
      <JobDialog job={job} onClose={() => setJob(null)} onFinished={finished} />
    </>
  )
}
