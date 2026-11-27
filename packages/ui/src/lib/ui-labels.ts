import * as React from "react"

/**
 * Text for the screen-reader labels inside shared components (the close button of a
 * dialog, the sidebar toggle). The app provides them in the user's language; the
 * defaults are English so the components work without a provider.
 */
export type UiLabels = { close: string; toggleSidebar: string }

const DEFAULT_LABELS: UiLabels = { close: "Close", toggleSidebar: "Toggle Sidebar" }

const UiLabelsContext = React.createContext<UiLabels>(DEFAULT_LABELS)

export function UiLabelsProvider({
  labels,
  children,
}: {
  labels: UiLabels
  children: React.ReactNode
}) {
  return React.createElement(UiLabelsContext.Provider, { value: labels }, children)
}

export function useUiLabels(): UiLabels {
  return React.useContext(UiLabelsContext)
}
