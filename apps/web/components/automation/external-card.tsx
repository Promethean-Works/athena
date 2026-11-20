"use client"

import * as React from "react"
import { PlugIcon, ServerIcon, WebhookIcon } from "lucide-react"

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
  const origin = useOrigin()
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PlugIcon className="size-4 text-muted-foreground" /> External
          automation
        </CardTitle>
        <CardDescription>
          Connect n8n, scripts or AI agents to Athena.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <FieldGroup className="gap-5">
          <Field>
            <FieldLabel htmlFor="automation-webhook-url">
              <WebhookIcon className="size-4 text-muted-foreground" /> Webhook
              URL
            </FieldLabel>
            <CopyUrl
              id="automation-webhook-url"
              label="Webhook URL"
              value={`${origin}/api/automation/webhook/<token>`}
            />
            <FieldDescription>
              Send a POST request to fire a webhook trigger; no sign-in needed.
              Each webhook trigger has its own token: copy its full URL from the
              trigger list.
            </FieldDescription>
          </Field>
          <Field>
            <FieldLabel htmlFor="automation-mcp-url">
              <ServerIcon className="size-4 text-muted-foreground" /> MCP server
            </FieldLabel>
            <CopyUrl
              id="automation-mcp-url"
              label="MCP server URL"
              value={`${origin}/api/mcp`}
            />
            <FieldDescription>
              Streamable HTTP. Clients sign in with a session cookie, or send
              the token set in the server&apos;s{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                ATHENA_MCP_TOKEN
              </code>{" "}
              environment variable as{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                Authorization: Bearer &lt;token&gt;
              </code>
              .
            </FieldDescription>
          </Field>
        </FieldGroup>
      </CardContent>
    </Card>
  )
}
