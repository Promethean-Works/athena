"use client"

import * as React from "react"
import { PlugIcon, ServerIcon, WebhookIcon } from "lucide-react"
import { Trans, useTranslation } from "react-i18next"

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

import { CopyUrl } from "@/components/automation/copy-url"

function useOrigin(): string {
  const [origin, setOrigin] = React.useState("")
  React.useEffect(() => setOrigin(window.location.origin), [])
  return origin
}

/** How n8n, scripts and MCP clients reach Athena. */
export function ExternalAutomationCard() {
  const { t } = useTranslation("automation")
  const origin = useOrigin()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PlugIcon className="size-4 text-muted-foreground" />{" "}
          {t("external.title")}
        </CardTitle>
        <CardDescription>
          {t("external.description")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-5">
          <Field>
            <FieldLabel htmlFor="automation-webhook-url">
              <WebhookIcon className="size-4 text-muted-foreground" />{" "}
              {t("external.webhookUrl")}
            </FieldLabel>
            <CopyUrl
              id="automation-webhook-url"
              label={t("external.webhookUrl")}
              value={`${origin}/api/automation/webhook/<token>`}
            />
            <FieldDescription>
              {t("external.webhookHint")}
            </FieldDescription>
          </Field>
          <Field>
            <FieldLabel htmlFor="automation-mcp-url">
              <ServerIcon className="size-4 text-muted-foreground" />{" "}
              {t("external.mcpServer")}
            </FieldLabel>
            <CopyUrl
              id="automation-mcp-url"
              label={t("external.mcpUrl")}
              value={`${origin}/api/mcp`}
            />
            <FieldDescription>
              <Trans
                i18nKey="external.mcpHint"
                ns="automation"
                shouldUnescape
                components={{
                  envVar: (
                    <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs" />
                  ),
                  authHeader: (
                    <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs" />
                  ),
                }}
              />
            </FieldDescription>
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
