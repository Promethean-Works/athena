"use client"

import * as React from "react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card"
import { FieldDescription, FieldGroup } from "@workspace/ui/components/field"
import { Skeleton } from "@workspace/ui/components/skeleton"

import { useAuth } from "@/components/auth-provider"
import { CopyField } from "@/components/settings/copy-field"

type SettingsFile = Schemas["SettingsFileOut"]

/** Settings → System: where the host-wide settings are saved, so an admin knows
 * which file to fix if a change keeps Athena from starting. Admins only. */
export function SettingsFileCard() {
  const { user } = useAuth()
  const [file, setFile] = React.useState<SettingsFile | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!user.is_admin) return
    api.GET("/api/settings/file").then(({ data, error }) => {
      if (data) setFile(data)
      else setError(errorMessage(error))
    })
  }, [user.is_admin])

  if (!user.is_admin) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Settings file</CardTitle>
        <CardDescription>
          The settings on these pages are saved in one file on the server. If a
          change keeps Athena from starting or locks you out, fix it there in
          any text editor, then restart Athena.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error !== null ? (
          <FieldDescription className="text-destructive">
            Couldn&apos;t load where the file is: {error}
          </FieldDescription>
        ) : file === null ? (
          <Skeleton className="h-16 w-full" />
        ) : (
          <FieldGroup>
            <CopyField id="settings-file-path" label="File" value={file.path} />
            <FieldDescription>
              <code>athena config check</code> on the server shows what&apos;s
              wrong with it, with line numbers. The version before the last save
              is kept next to it as <code>athena.json.bak</code>.
            </FieldDescription>
          </FieldGroup>
        )}
      </CardContent>
    </Card>
  )
}
