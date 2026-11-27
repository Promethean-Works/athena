"use client"

import * as React from "react"
import { ArrowUpCircleIcon } from "lucide-react"
import { useTranslation } from "react-i18next"

import { type Schemas } from "@workspace/api-client"
import { Button } from "@workspace/ui/components/button"

import { useAuth } from "@/components/auth-provider"
import {
  useCapabilities,
  useCapability,
} from "@/components/capabilities-provider"
import { CopyField } from "@/components/settings/copy-field"
import { UpdateAthenaDialog } from "@/components/update-athena-dialog"

type UpdateInfo = Schemas["UpdateInfo"]

/**
 * The way to install a newer release: the **Update now** button when this host can update
 * itself (the `self_update` capability), otherwise why it can't and the command to run
 * on the server. Renders nothing for non-admins and while the capabilities load.
 */
export function UpdateAction({ info }: { info: UpdateInfo }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const { manifest } = useCapabilities()
  const capability = useCapability("self_update")
  const [open, setOpen] = React.useState(false)
  if (!user.is_admin || manifest === null || !info.latest) return null

  if (capability?.available) {
    return (
      <>
        <Button className="self-start" onClick={() => setOpen(true)}>
          <ArrowUpCircleIcon data-icon="inline-start" />
          {t("update.action.updateNow")}
        </Button>
        {open ? (
          <UpdateAthenaDialog
            current={info.current}
            latest={info.latest}
            releaseUrl={info.release_url ?? null}
            onClose={() => setOpen(false)}
          />
        ) : null}
      </>
    )
  }
  return (
    <>
      <p>
        {t("update.action.howTo", {
          reason: (
            capability?.detail ?? t("update.action.cannotSelf")
          ).replace(/\.$/, ""),
        })}
      </p>
      <CopyField
        id="update-command"
        label={t("update.action.commandLabel")}
        value={info.command}
      />
    </>
  )
}
