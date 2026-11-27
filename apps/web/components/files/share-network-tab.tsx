"use client"

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"

import { AlertCircleIcon } from "lucide-react"

import { api, errorMessage, type Schemas } from "@workspace/api-client"
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@workspace/ui/components/alert"
import { Field, FieldError, FieldLabel } from "@workspace/ui/components/field"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Switch } from "@workspace/ui/components/switch"
import { Button } from "@workspace/ui/components/button"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
import { useCapability } from "@/components/capabilities-provider"
import {
  ConnectionString,
  serverHost,
} from "@/components/files/connection-string"
import { canCreateShare } from "@/components/files/elevation"
import { NfsShareForm } from "@/components/files/nfs-share-form"
import { ShareCapabilityNotice } from "@/components/files/share-capability-notice"
import { SmbShareForm } from "@/components/files/smb-share-form"

type Target = {
  location: number
  remote?: string
  path: string
  name: string
  kind: string
}

/** The "Network" tab of the explorer's Share dialog: publish this folder over SMB or NFS.
 * A local folder is shared in place (inside its location); a folder on a cloud remote is
 * mounted first, then shared. */
export function ShareNetworkTab({ target }: { target: Target }) {
  const { t } = useTranslation("files")
  if (target.remote) {
    return <RemoteMountGate remote={target.remote} path={target.path} />
  }
  if (target.kind !== "dir") {
    return (
      <p className="text-sm text-muted-foreground">
        {t("shareDialog.networkFolderOnly")}
      </p>
    )
  }
  return (
    <LocationShares
      locationId={target.location}
      folder={target.path}
      name={target.name}
    />
  )
}

/** A cloud folder has to be mounted on this computer before it can be shared. */
function RemoteMountGate({ remote, path }: { remote: string; path: string }) {
  const { t } = useTranslation("files")
  const mountCap = useCapability("cloud.mount")
  const [mount, setMount] = React.useState<
    Schemas["MountOut"] | null | undefined
  >(undefined)
  const [readOnly, setReadOnly] = React.useState(true)
  const [pending, setPending] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    void (async () => {
      const { data } = await api.GET("/api/cloud/mounts")
      setMount(
        (data ?? []).find((m) => m.remote === remote && m.path === path) ?? null
      )
    })()
  }, [remote, path])

  async function mountIt() {
    setPending(true)
    setError(null)
    const { data, error: err } = await api.POST("/api/cloud/mounts", {
      body: { remote, path, read_only: readOnly },
    })
    setPending(false)
    if (!data) {
      setError(errorMessage(err))
      return
    }
    setMount(data)
  }

  if (mountCap?.status !== "ready") {
    return (
      <Alert>
        <AlertCircleIcon />
        <AlertTitle>{t("shareDialog.mountUnavailable")}</AlertTitle>
        <AlertDescription>
          {mountCap?.detail ?? t("network.notice.fallback")}
        </AlertDescription>
      </Alert>
    )
  }
  if (mount === undefined) return <Skeleton className="h-24 w-full" />
  if (mount) {
    return (
      <LocationShares locationId={mount.location_id} folder="" name={remote} />
    )
  }
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        {t("shareDialog.mountDescription")}
      </p>
      <Field orientation="horizontal">
        <Switch
          id="mount-read-only"
          checked={readOnly}
          onCheckedChange={setReadOnly}
          disabled={pending}
        />
        <FieldLabel htmlFor="mount-read-only">
          {t("shareDialog.mountReadOnly")}
        </FieldLabel>
      </Field>
      {error ? <FieldError>{error}</FieldError> : null}
      <div className="flex justify-end">
        <Button onClick={() => void mountIt()} disabled={pending}>
          {pending ? <Spinner /> : null}
          {t("shareDialog.mountAction")}
        </Button>
      </div>
    </div>
  )
}

/** The SMB and NFS tabs for one folder of a file location (`folder` is relative to it,
 * "" for the location itself), with the folder's existing shares. */
function LocationShares({
  locationId,
  folder,
  name,
}: {
  locationId: number
  folder: string
  name: string
}) {
  const { t } = useTranslation("files")
  const smb = useCapability("shares.smb")
  const nfs = useCapability("shares.nfs")
  const [smbShares, setSmbShares] = React.useState<Schemas["SmbShareOut"][]>([])
  const [nfsShares, setNfsShares] = React.useState<Schemas["NfsShareOut"][]>([])

  const load = React.useCallback(async () => {
    const [a, b] = await Promise.all([
      api.GET("/api/shares/smb"),
      api.GET("/api/shares/nfs"),
    ])
    const here = (s: { location_id: number; folder: string }) =>
      s.location_id === locationId && s.folder === folder
    setSmbShares((a.data ?? []).filter(here))
    setNfsShares((b.data ?? []).filter(here))
  }, [locationId, folder])
  React.useEffect(() => {
    void load()
  }, [load])

  const actions =
    (formId: string) =>
    ({ pending }: { pending: boolean }) => (
      <div className="flex justify-end gap-2">
        <Button
          variant="outline"
          render={<Link href="/files/network/" />}
          nativeButton={false}
        >
          {t("network.allShares")}
        </Button>
        <Button type="submit" form={formId} disabled={pending}>
          {pending ? <Spinner /> : null}
          {t("smb.createShare")}
        </Button>
      </div>
    )

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        {t("shareDialog.networkDescription")}
      </p>
      <Tabs defaultValue="smb">
        <TabsList>
          <TabsTrigger value="smb">{t("network.tabSmb")}</TabsTrigger>
          <TabsTrigger value="nfs">{t("network.tabNfs")}</TabsTrigger>
        </TabsList>
        <TabsContent value="smb" className="flex flex-col gap-3 pt-2">
          {smbShares.map((s) => (
            <ConnectionString
              key={s.id}
              value={`\\\\${serverHost()}\\${s.name}`}
              label={t("network.smbAddress")}
            />
          ))}
          <ShareCapabilityNotice capability={smb} kind="SMB" />
          {canCreateShare(smb) ? (
            <SmbShareForm
              id="explorer-smb-share"
              locations={null}
              fixedLocation={locationId}
              folder={folder}
              defaultName={name}
              onCreated={() => void load()}
              actions={actions("explorer-smb-share")}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="nfs" className="flex flex-col gap-3 pt-2">
          {nfsShares.map((s) => (
            <ConnectionString
              key={s.id}
              value={`${serverHost()}:${s.path}`}
              label={t("network.nfs.address")}
            />
          ))}
          <ShareCapabilityNotice capability={nfs} kind="NFS" />
          {canCreateShare(nfs) ? (
            <NfsShareForm
              id="explorer-nfs-share"
              locations={null}
              fixedLocation={locationId}
              folder={folder}
              onCreated={() => void load()}
              actions={actions("explorer-nfs-share")}
            />
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
  )
}
