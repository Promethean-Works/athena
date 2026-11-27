import * as React from "react"

// Athena's mark: a gradient "A" (also a house, for the home server) with a status light.
// Keep in step with site/favicon.svg and apps/web/app/icon.svg.
export function Logo({ className }: { className?: string }) {
  const id = React.useId()
  const gradient = `${id}-g`
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden="true"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset=".55" stopColor="#8b5cf6" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill="#0e0e12" />
      <path
        fill={`url(#${gradient})`}
        fillRule="evenodd"
        d="M8 56V29L32 7l24 22v27H46V44H18v12zM18 29.8 32 17l14 12.8V35H18z"
      />
      <circle cx="32" cy="29" r="3" fill={`url(#${gradient})`} />
    </svg>
  )
}
