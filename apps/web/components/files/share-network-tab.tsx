"use client"

import * as React from "react"
import Link from "next/link"
import { useTranslation } from "react-i18next"

import { api, type Schemas } from "@workspace/api-client"
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

type Target = { location: number; path: string; name: string; kind: string }

/** The "Network" tab of the explorer's Share dialog: publish this location over SMB or NFS.
 * Only a location's top folder can be shared (the shares are per location). */
export function ShareNetworkTab({ target }: { target: Target }) {
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
    setSmbShares(
      (a.data ?? []).filter((s) => s.location_id === target.location)
    )
    setNfsShares(
      (b.data ?? []).filter((s) => s.location_id === target.location)
    )
  }, [target.location])
  React.useEffect(() => {
    void load()
  }, [load])

  if (target.kind !== "dir") {
    return (
      <p className="text-sm text-muted-foreground">
        {t("shareDialog.networkFolderOnly")}
      </p>
    )
  }
  if (target.path !== "") {
    return (
      <p className="text-sm text-muted-foreground">
        {t("shareDialog.networkRootOnly")}
      </p>
    )
  }

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
              fixedLocation={target.location}
              defaultName={target.name}
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
              fixedLocation={target.location}
              onCreated={() => void load()}
              actions={actions("explorer-nfs-share")}
            />
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
  )
}
