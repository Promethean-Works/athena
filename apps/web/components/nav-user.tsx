"use client"

import * as React from "react"
import {
  EllipsisVerticalIcon,
  GlobeIcon,
  LogOutIcon,
  RotateCwIcon,
} from "lucide-react"

import { useAuth } from "@/components/auth-provider"
import { RestartAthenaDialog } from "@/components/restart-athena"
import { TunnelAddressDialog } from "@/components/tunnel/tunnel-address-dialog"
import { Avatar, AvatarFallback } from "@workspace/ui/components/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu"
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@workspace/ui/components/sidebar"

// From the dashboard-01 block: the signed-in admin in the sidebar footer.
export function NavUser() {
  const { isMobile } = useSidebar()
  const { user, logout } = useAuth()
  const [confirmRestart, setConfirmRestart] = React.useState(false)
  const [showTunnel, setShowTunnel] = React.useState(false)
  const initials = user.username.slice(0, 2).toUpperCase()
  const role = user.is_admin ? "Administrator" : "User"

  return (
    <>
      <SidebarMenu>
        <SidebarMenuItem>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <SidebarMenuButton
                  size="lg"
                  className="aria-expanded:bg-muted"
                />
              }
            >
              <Avatar className="size-8 rounded-lg">
                <AvatarFallback className="rounded-lg">
                  {initials}
                </AvatarFallback>
              </Avatar>
              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">{user.username}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {role}
                </span>
              </div>
              <EllipsisVerticalIcon className="ml-auto size-4" />
            </DropdownMenuTrigger>
            <DropdownMenuContent
              className="min-w-56"
              side={isMobile ? "bottom" : "right"}
              align="end"
              sideOffset={4}
            >
              <DropdownMenuGroup>
                <DropdownMenuLabel className="p-0 font-normal">
                  <div className="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                    <Avatar className="size-8 rounded-lg">
                      <AvatarFallback className="rounded-lg">
                        {initials}
                      </AvatarFallback>
                    </Avatar>
                    <div className="grid flex-1 text-left text-sm leading-tight">
                      <span className="truncate font-medium">
                        {user.username}
                      </span>
                      <span className="truncate text-xs text-muted-foreground">
                        {role}
                      </span>
                    </div>
                  </div>
                </DropdownMenuLabel>
              </DropdownMenuGroup>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                <DropdownMenuItem onClick={() => setShowTunnel(true)}>
                  <GlobeIcon />
                  Tunnel address
                </DropdownMenuItem>
                {user.is_admin ? (
                  <DropdownMenuItem onClick={() => setConfirmRestart(true)}>
                    <RotateCwIcon />
                    Restart Athena
                  </DropdownMenuItem>
                ) : null}
                <DropdownMenuItem onClick={logout}>
                  <LogOutIcon />
                  Log out
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarMenuItem>
      </SidebarMenu>
      <TunnelAddressDialog open={showTunnel} onOpenChange={setShowTunnel} />
      <RestartAthenaDialog
        open={confirmRestart}
        onOpenChange={setConfirmRestart}
      />
    </>
  )
}
