"use client"

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
    return <Quiet>Couldn&apos;t load remote access: {state.error}</Quiet>

  const { status, enabled, provider } = state.data
  if (!enabled)
    return (
      <Quiet>
        Off. Turn it on in Settings → System to reach Athena from outside your
        network.
      </Quiet>
    )
  const url = status.public_url
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm">
        {status.running ? (
          <Badge>Running</Badge>
        ) : (
          <Badge variant="outline">Not running</Badge>
        )}
        <span className="text-muted-foreground">
          {PROVIDERS[provider ?? ""] ?? provider ?? "No provider"}
        </span>
      </div>
      {url ? (
        <InputGroup>
          <InputGroupInput
            readOnly
            value={url}
            aria-label="Public address"
            className="font-mono"
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              size="icon-xs"
              aria-label="Copy public address"
              onClick={async () => {
                const ok = await copyText(url)
                toast.add(
                  ok
                    ? { type: "success", title: "Address copied" }
                    : { type: "error", title: "Couldn't copy" }
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
  return (
    <DashboardCard
      icon={GlobeIcon}
      title="Remote access"
      description="Reach Athena from outside your network."
      href="/settings/system/"
      linkLabel="Settings"
    >
      <RemoteBody />
    </DashboardCard>
  )
}
