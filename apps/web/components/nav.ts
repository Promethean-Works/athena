import type { LucideIcon } from "lucide-react"
import {
  BoxIcon,
  CircleHelpIcon,
  ClockIcon,
  CloudIcon,
  FolderIcon,
  LayoutDashboardIcon,
  LayoutGridIcon,
  LayoutListIcon,
  PackageIcon,
  Settings2Icon,
  Share2Icon,
  SparklesIcon,
  SquareTerminalIcon,
  StoreIcon,
} from "lucide-react"

export type NavItem = {
  title: string
  url: string
  icon: LucideIcon
  /**
   * Capability id from the server's manifest (M1). Items whose capability is
   * missing on this host are hidden. Undefined means always shown.
   */
  capability?: string
  /**
   * Also show the item when the capability is stopped or not installed (but relevant
   * to this OS), so the page can offer Start or setup instructions.
   */
  showWhenUnavailable?: boolean
  external?: boolean
}

// Sections are added here as their milestones land (Apps, Store, Packages, Files,
// Cloud, Terminal, Assistant, Settings), so the sidebar never links to a missing page.
export const navMain: NavItem[] = [
  { title: "Dashboard", url: "/", icon: LayoutDashboardIcon },
  {
    title: "Apps",
    url: "/apps/",
    icon: LayoutGridIcon,
    capability: "containers",
    showWhenUnavailable: true,
  },
  {
    title: "Store",
    url: "/store/",
    icon: StoreIcon,
    capability: "containers",
    showWhenUnavailable: true,
  },
  {
    title: "Packages",
    url: "/packages/",
    icon: PackageIcon,
    // Shown when any package manager is installed, even one that needs root, so the
    // page can say why it can't be used.
    capability: "packages.*",
    showWhenUnavailable: true,
  },
  {
    title: "Automation",
    url: "/automation/",
    icon: ClockIcon,
    capability: "automation",
  },
  {
    title: "Files",
    url: "/files/",
    icon: FolderIcon,
    capability: "files",
  },
  {
    title: "Network shares",
    url: "/files/network/",
    icon: Share2Icon,
    // Shown even when the host can't create shares yet, so the page can say why
    // and how to set it up (SMB and NFS each have their own capability).
    capability: "shares.smb",
    showWhenUnavailable: true,
  },
  {
    title: "Cloud",
    url: "/cloud/",
    icon: CloudIcon,
    // Shown without rclone too, so the page can say how to install it.
    capability: "cloud.rclone",
    showWhenUnavailable: true,
  },
  {
    title: "Containers",
    url: "/containers/",
    icon: BoxIcon,
    capability: "containers",
    showWhenUnavailable: true,
  },
  {
    title: "Terminal",
    url: "/terminal/",
    icon: SquareTerminalIcon,
    capability: "terminal.host",
  },
  { title: "Assistant", url: "/assistant/", icon: SparklesIcon },
  {
    title: "Backups",
    url: "/backups/",
    icon: LayoutListIcon,
    capability: "backup",
  },
]

/** True when `pathname` is the item's page or below it ("/" only matches itself). */
export function isActive(item: NavItem, pathname: string): boolean {
  if (item.url === "/") return pathname === "/"
  return pathname.startsWith(item.url.replace(/\/$/, ""))
}

export const navSecondary: NavItem[] = [
  { title: "Settings", url: "/settings/", icon: Settings2Icon },
  {
    title: "Help",
    url: "https://github.com/Promethean-Works/athena#readme",
    icon: CircleHelpIcon,
    external: true,
  },
]

/** Title for the header, from the nav item matching the current path. */
export function titleForPath(pathname: string): string {
  const match = [...navMain, ...navSecondary].find(
    (item) => !item.external && isActive(item, pathname)
  )
  return match?.title ?? "Athena"
}
