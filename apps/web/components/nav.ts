import type { ParseKeys } from "i18next"
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
  /** Key in the `nav` namespace. */
  titleKey: ParseKeys<"nav">
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
  { titleKey: "dashboard", url: "/", icon: LayoutDashboardIcon },
  {
    titleKey: "apps",
    url: "/apps/",
    icon: LayoutGridIcon,
    capability: "containers",
    showWhenUnavailable: true,
  },
  {
    titleKey: "store",
    url: "/store/",
    icon: StoreIcon,
    capability: "containers",
    showWhenUnavailable: true,
  },
  {
    titleKey: "packages",
    url: "/packages/",
    icon: PackageIcon,
    // Shown when any package manager is installed, even one that needs root, so the
    // page can say why it can't be used.
    capability: "packages.*",
    showWhenUnavailable: true,
  },
  {
    titleKey: "automation",
    url: "/automation/",
    icon: ClockIcon,
    capability: "automation",
  },
  {
    titleKey: "files",
    url: "/files/",
    icon: FolderIcon,
    capability: "files",
  },
  {
    titleKey: "smbShares",
    url: "/files/smb/",
    icon: Share2Icon,
    // Shown even when Samba isn't installed yet, so the page can say how to set it
    // up. Hidden on macOS and Windows where share creation is unsupported.
    capability: "shares.smb",
    showWhenUnavailable: true,
  },
  {
    titleKey: "cloud",
    url: "/cloud/",
    icon: CloudIcon,
    // Shown without rclone too, so the page can say how to install it.
    capability: "cloud.rclone",
    showWhenUnavailable: true,
  },
  {
    titleKey: "containers",
    url: "/containers/",
    icon: BoxIcon,
    capability: "containers",
    showWhenUnavailable: true,
  },
  {
    titleKey: "terminal",
    url: "/terminal/",
    icon: SquareTerminalIcon,
    capability: "terminal.host",
  },
  { titleKey: "assistant", url: "/assistant/", icon: SparklesIcon },
  {
    titleKey: "backups",
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
  { titleKey: "settings", url: "/settings/", icon: Settings2Icon },
  {
    titleKey: "help",
    url: "https://github.com/Promethean-Works/athena#readme",
    icon: CircleHelpIcon,
    external: true,
  },
]

/** Title key for the header, from the nav item matching the current path. */
export function titleKeyForPath(pathname: string): ParseKeys<"nav"> | null {
  const match = [...navMain, ...navSecondary].find(
    (item) => !item.external && isActive(item, pathname)
  )
  return match?.titleKey ?? null
}
