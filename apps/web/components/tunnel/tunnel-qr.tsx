"use client"

import { QRCodeSVG } from "qrcode.react"

/** A QR code for the tunnel address. Always black on white so phones can scan it in dark mode too. */
export function TunnelQr({
  value,
  size = 176,
}: {
  value: string
  size?: number
}) {
  return (
    <div className="w-fit rounded-lg border bg-white p-3">
      <QRCodeSVG
        value={value}
        size={size}
        marginSize={0}
        role="img"
        title="QR code for the tunnel address"
      />
    </div>
  )
}
