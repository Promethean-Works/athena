"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { FieldError } from "@workspace/ui/components/field"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"
import { Spinner } from "@workspace/ui/components/spinner"

/** How long the password is kept after it was last used. */
export const HOST_PASSWORD_IDLE_MS = 5 * 60 * 1000

type HostPassword = {
  /** The computer's password: the one kept from a recent use, or asked for in a dialog.
   * `null` when the admin cancels. `reason` says what it is for ("Create SMB share"). */
  ask: (reason: string) => Promise<string | null>
  /** Keep a password that just worked, so the next action within 5 minutes doesn't ask. */
  remember: (password: string) => void
  /** Drop it now: call this when the server refused it or an action failed. */
  forget: () => void
}

const HostPasswordContext = React.createContext<HostPassword | null>(null)

type Asking = { reason: string; resolve: (password: string | null) => void }

/**
 * One place that asks for the computer's password (the account Athena runs as, for
 * `sudo`), so every feature that needs it shares the dialog and the session.
 *
 * The password only ever lives in this component's memory: never in storage, cookies,
 * the URL or logs. It is kept only after an action it unlocked worked, for
 * `HOST_PASSWORD_IDLE_MS` after its last use, and is dropped on a failure, when the tab
 * hides for good (page unload), and when the signed-in layout unmounts (sign-out).
 */
export function HostPasswordProvider({
  children,
}: {
  children: React.ReactNode
}) {
  const { t } = useTranslation("common")
  const kept = React.useRef<string | null>(null)
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null)
  const [asking, setAsking] = React.useState<Asking | null>(null)
  const [value, setValue] = React.useState("")
  const input = React.useRef<HTMLInputElement>(null)
  const [checking, setChecking] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const forget = React.useCallback(() => {
    kept.current = null
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
  }, [])

  const remember = React.useCallback(
    (password: string) => {
      forget()
      kept.current = password
      timer.current = setTimeout(forget, HOST_PASSWORD_IDLE_MS)
    },
    [forget]
  )

  const ask = React.useCallback(
    (reason: string) => {
      if (kept.current !== null) {
        // Using it again restarts the idle time.
        remember(kept.current)
        return Promise.resolve(kept.current)
      }
      return new Promise<string | null>((resolve) => {
        setValue("")
        setError(null)
        // A second request while the dialog is open replaces the first, which is cancelled.
        setAsking((previous) => {
          previous?.resolve(null)
          return { reason, resolve }
        })
      })
    },
    [remember]
  )

  React.useEffect(() => {
    window.addEventListener("pagehide", forget)
    return () => {
      window.removeEventListener("pagehide", forget)
      forget()
    }
  }, [forget])

  function finish(password: string | null) {
    asking?.resolve(password)
    setAsking(null)
    setValue("")
    setError(null)
  }

  // Check the password with the server before the action runs, so a typo is caught here.
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!value || checking) return
    setChecking(true)
    setError(null)
    const { response, error: err } = await api.POST(
      "/api/system/host-password/check",
      { body: { password: value } }
    )
    setChecking(false)
    // 409: this host doesn't ask for a password, so there is nothing to check.
    if (response.ok || response.status === 409) return finish(value)
    setError(errorMessage(err))
    setValue("")
    // The button the admin clicked was disabled during the check and dropped focus.
    requestAnimationFrame(() => input.current?.focus())
  }

  const session = React.useMemo(
    () => ({ ask, remember, forget }),
    [ask, remember, forget]
  )

  return (
    <HostPasswordContext.Provider value={session}>
      {children}
      <Dialog open={asking !== null} onOpenChange={(o) => !o && finish(null)}>
        <DialogContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => void submit(e)}
          >
            <DialogHeader>
              <DialogTitle>{t("hostPassword.title")}</DialogTitle>
              <DialogDescription>
                {t("hostPassword.description", {
                  reason: asking?.reason ?? "",
                })}
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-2">
              <Label htmlFor="host-password">{t("hostPassword.label")}</Label>
              <Input
                id="host-password"
                ref={input}
                type="password"
                autoComplete="current-password"
                autoFocus
                value={value}
                onChange={(e) => setValue(e.target.value)}
                readOnly={checking}
                aria-invalid={error !== null}
              />
              {error ? <FieldError>{error}</FieldError> : null}
              <p className="text-sm text-muted-foreground">
                {t("hostPassword.keep", {
                  minutes: HOST_PASSWORD_IDLE_MS / 60000,
                })}
              </p>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => finish(null)}
              >
                {t("cancel")}
              </Button>
              <Button type="submit" disabled={!value || checking}>
                {checking ? <Spinner /> : null}
                {t("hostPassword.continue")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </HostPasswordContext.Provider>
  )
}

export function useHostPassword(): HostPassword {
  const ctx = React.useContext(HostPasswordContext)
  if (!ctx) throw new Error("useHostPassword needs HostPasswordProvider")
  return ctx
}
