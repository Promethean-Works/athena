"use client"

import { Trans, useTranslation } from "react-i18next"
import { CopyIcon, GlobeIcon } from "lucide-react"

import { api } from "@workspace/api-client"
import { Badge } from "@workspace/ui/components/badge"
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from "@workspace/ui/components/input-group"
import { toast } from "@workspace/ui/components/toast"

import {
  DashboardCard,
  Quiet,
  RowsSkeleton,
} from "@/components/dashboard/card-shell"
import { useApi } from "@/hooks/use-api"
import { copyText } from "@/lib/clipboard"

const PROVIDERS: Record<string, string> = {
  cloudflare: "Cloudflare Tunnel",
  tailscale: "Tailscale Funnel",
  ngrok: "ngrok",
}

function RemoteBody() {
  const { t } = useTranslation("dashboard")
  const state = useApi(async () => {
    const [status, system] = await Promise.all([
      api.GET("/api/tunnel/status"),
      api.GET("/api/settings/system"),
    ])
    return {
      data:
        status.data && system.data
          ? { status: status.data, enabled: system.data.tunnel_enabled, provider: system.data.tunnel_provider }
          : undefined,
      response: status.data ? system.response : status.response,
    }
  }, 30000)
  if (state.status === "loading") return <RowsSkeleton rows={2} />
  if (state.status === "error")
    return <Quiet>{t("remote.loadError", { error: state.error })}</Quiet>

  const { status, enabled, provider } = state.data
  if (!enabled)
    return (
      <Quiet>{t("remote.off")}</Quiet>
    )
  const url = status.public_url
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm">
        {status.running ? (
          <Badge>{t("remote.running")}</Badge>
        ) : (
          <Badge variant="outline">{t("remote.notRunning")}</Badge>
        )}
        <span className="text-muted-foreground">
          {PROVIDERS[provider ?? ""] ?? provider ?? t("remote.noProvider")}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        <Trans
          i18nKey="remote.warning"
          ns="dashboard"
          components={{
            link: <a className="underline" href="/settings/system/" />,
          }}
        />
      </p>
      {url ? (
        <InputGroup>
          <InputGroupInput
            readOnly
            value={url}
            aria-label={t("remote.publicAddress")}
            className="font-mono"
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              size="icon-xs"
              aria-label={t("remote.copyAddress")}
              onClick={async () => {
                const ok = await copyText(url)
                toast.add(
                  ok
                    ? { type: "success", title: t("remote.copied") }
                    : { type: "error", title: t("remote.copyFailed") }
                )
              }}
            >
              <CopyIcon />
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      ) : status.detail ? (
        <p className="text-sm text-muted-foreground">{status.detail}</p>
      ) : null}
    </div>
  )
}

export function RemoteAccessCard() {
  const { t } = useTranslation("dashboard")
  return (
    <DashboardCard
      icon={GlobeIcon}
      title={t("remote.title")}
      description={t("remote.description")}
      href="/settings/system/"
      linkLabel={t("remote.settings")}
    >
      <RemoteBody />
    </DashboardCard>
  )
}
