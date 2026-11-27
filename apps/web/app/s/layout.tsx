import type { Metadata } from "next"
import { Logo } from "@/components/logo"

export const metadata: Metadata = {
  title: "Shared with you",
  // The address is the secret; keep it out of other sites' logs.
  referrer: "no-referrer",
  robots: { index: false, follow: false },
}

// /s/<token>: a share link's page. Outside the app shell and needs no session.
export default function ShareLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-svh flex-col items-center bg-muted px-4 py-6 md:p-10">
      <div className="flex w-full max-w-3xl flex-col gap-6">
        <div className="flex items-center gap-2 self-center font-medium">
          <Logo className="size-6" />
          Athena
        </div>
        {children}
      </div>
    </div>
  )
}
