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
  /** Hidden from users who aren't admins (the API refuses them too). */
  adminOnly?: boolean
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
    adminOnly: true,
    url: "/packages/",
    icon: PackageIcon,
    // Shown when any package manager is installed, even one that needs root, so the
    // page can say why it can't be used.
    capability: "packages.*",
    showWhenUnavailable: true,
  },
  {
    titleKey: "automation",
    adminOnly: true,
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
    titleKey: "networkShares",
    adminOnly: true,
    url: "/files/network/",
    icon: Share2Icon,
    // Shown even when the host can't create shares yet, so the page can say why
    // and how to set it up (SMB and NFS each have their own capability).
    capability: "shares.smb",
    showWhenUnavailable: true,
  },
  {
    titleKey: "cloud",
    adminOnly: true,
    url: "/cloud/",
    icon: CloudIcon,
    // Shown without rclone too, so the page can say how to install it.
    capability: "cloud.rclone",
    showWhenUnavailable: true,
  },
  {
    titleKey: "containers",
    adminOnly: true,
    url: "/containers/",
    icon: BoxIcon,
    capability: "containers",
    showWhenUnavailable: true,
  },
  {
    titleKey: "terminal",
    adminOnly: true,
    url: "/terminal/",
    icon: SquareTerminalIcon,
    capability: "terminal.host",
  },
  {
    titleKey: "assistant",
    adminOnly: true,
    url: "/assistant/",
    icon: SparklesIcon,
  },
  {
    titleKey: "backups",
    adminOnly: true,
    url: "/backups/",
    icon: LayoutListIcon,
    capability: "backup",
  },
]

function matches(item: NavItem, pathname: string): boolean {
  if (item.url === "/") return pathname === "/"
  return pathname.startsWith(item.url.replace(/\/$/, ""))
}

/** The item for `pathname`: the longest url that matches, so /files/network/ isn't also Files. */
function best(pathname: string): NavItem | undefined {
  return [...navMain, ...navSecondary]
    .filter((item) => !item.external && matches(item, pathname))
    .sort((x, y) => y.url.length - x.url.length)[0]
}

/** True when `item` is the most specific nav entry for `pathname`. */
export function isActive(item: NavItem, pathname: string): boolean {
  return best(pathname) === item
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

// Pages inside an otherwise open section that only admins may use.
const ADMIN_ONLY_PATHS = [
  "/settings/system/",
  "/settings/https/",
  "/settings/ai/",
  "/settings/users/",
  "/apps/new/",
  "/apps/view/",
  "/store/catalogs/",
]

/** True when `pathname` is a page only admins may open (nav items and extra pages). */
export function isAdminPath(pathname: string): boolean {
  const path = pathname.endsWith("/") ? pathname : `${pathname}/`
  return (
    ADMIN_ONLY_PATHS.some((prefix) => path.startsWith(prefix)) ||
    navMain.some((item) => item.adminOnly && matches(item, pathname))
  )
}

/** Title key for the header, from the nav item matching the current path. */
export function titleKeyForPath(pathname: string): ParseKeys<"nav"> | null {
  return best(pathname)?.titleKey ?? null
}
