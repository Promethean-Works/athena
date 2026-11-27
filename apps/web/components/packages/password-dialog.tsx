"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import { Input } from "@workspace/ui/components/input"
import { Label } from "@workspace/ui/components/label"

type Asking = { name: string; resolve: (password: string | null) => void }

/**
 * Asks for the computer's password before an action that needs `sudo` (a manager that
 * reports `elevation: "password"`). The password is held in memory for that one request:
 * `ask()` resolves with it, or `null` if the admin cancels.
 */
export function usePasswordPrompt() {
  const { t } = useTranslation("packages")
  const [asking, setAsking] = React.useState<Asking | null>(null)
  const [value, setValue] = React.useState("")

  const ask = React.useCallback(
    (name: string) =>
      new Promise<string | null>((resolve) => {
        setValue("")
        setAsking({ name, resolve })
      }),
    []
  )

  function finish(password: string | null) {
    asking?.resolve(password)
    setAsking(null)
    setValue("")
  }

  const dialog = (
    <Dialog open={asking !== null} onOpenChange={(o) => !o && finish(null)}>
      <DialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (value) finish(value)
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("password.title")}</DialogTitle>
            <DialogDescription>
              {t("password.description", { name: asking?.name ?? "" })}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="package-password">{t("password.label")}</Label>
            <Input
              id="package-password"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => finish(null)}
            >
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!value}>
              {t("password.continue")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )

  return { ask, dialog }
}
