"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { api, errorMessage, setCsrfToken } from "@workspace/api-client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"

import { CapabilitiesProvider } from "@/components/capabilities-provider"
import { CredentialsForm } from "@/components/credentials-form"
import { AiSetupStep } from "@/components/settings/ai-setup-step"

export default function SetupPage() {
  const router = useRouter()
  const [step, setStep] = React.useState<"account" | "ai">("account")

  // Setup only makes sense on first run (checked once, before the account exists).
  React.useEffect(() => {
    api.GET("/api/auth/status").then(({ data }) => {
      if (data && !data.setup_required)
        router.replace(data.user ? "/" : "/login/")
    })
  }, [router])

  if (step === "ai")
    return (
      <CapabilitiesProvider>
        <AiSetupStep onDone={() => router.replace("/")} />
      </CapabilitiesProvider>
    )

  return (
    <Card>
      <CardHeader className="text-center">
        <CardTitle className="text-xl">Welcome to Athena</CardTitle>
        <CardDescription>
          Create the administrator account for this server.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <CredentialsForm
          mode="setup"
          submitLabel="Create account"
          onSubmit={async (credentials) => {
            const { data, error } = await api.POST("/api/auth/setup", {
              body: credentials,
            })
            if (!data) return errorMessage(error, "Couldn't create the account")
            setCsrfToken(data.csrf_token ?? null)
            setStep("ai")
            return null
          }}
        />
      </CardContent>
    </Card>
  )
}
