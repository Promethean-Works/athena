"use client"

import Link from "next/link"
import { ArrowLeftIcon } from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@workspace/ui/components/tabs"
import { NfsSharesPanel } from "@/components/files/nfs-shares-panel"
import { SmbSharesPanel } from "@/components/files/smb-shares-panel"

/** /files/network: publish file locations over SMB and NFS where the host can. */
export function NetworkSharesView() {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          render={<Link href="/files/" />}
          nativeButton={false}
        >
          <ArrowLeftIcon />
          Files
        </Button>
        <h2 className="font-heading text-lg font-medium">Network shares</h2>
      </div>

      <Tabs defaultValue="smb">
        <TabsList>
          <TabsTrigger value="smb">SMB</TabsTrigger>
          <TabsTrigger value="nfs">NFS</TabsTrigger>
        </TabsList>
        <TabsContent value="smb" className="pt-2">
          <SmbSharesPanel />
        </TabsContent>
        <TabsContent value="nfs" className="pt-2">
          <NfsSharesPanel />
        </TabsContent>
      </Tabs>
    </div>
  )
}
