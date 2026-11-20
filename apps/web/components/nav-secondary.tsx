"use client"

import * as React from "react"
import Link from "next/link"

import type { NavItem } from "@/components/nav"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@workspace/ui/components/sidebar"

export function NavSecondary({
  items,
  children,
  ...props
}: {
  items: NavItem[]
  /** Extra menu items after the links, e.g. ones that open a dialog. */
  children?: React.ReactNode
} & React.ComponentPropsWithoutRef<typeof SidebarGroup>) {
  return (
    <SidebarGroup {...props}>
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => (
            <SidebarMenuItem key={item.title}>
              <SidebarMenuButton
                render={
                  item.external ? (
                    <a href={item.url} target="_blank" rel="noreferrer" />
                  ) : (
                    <Link href={item.url} />
                  )
                }
              >
                <item.icon />
                <span>{item.title}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
          {children}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}
