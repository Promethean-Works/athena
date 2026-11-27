"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"

import { api, errorMessage } from "@workspace/api-client"
import { toast } from "@workspace/ui/components/toast"

import {
  CARDS_BY_ID,
  DEFAULT_LAYOUT,
  type LayoutCard,
} from "@/components/dashboard/cards"

/** Drops ids this UI doesn't know (an older UI reading a newer layout). */
function known(cards: LayoutCard[]): LayoutCard[] {
  return cards.filter((c) => CARDS_BY_ID.has(c.id))
}

const sameLayout = (a: LayoutCard[], b: LayoutCard[]) =>
  a.length === b.length &&
  a.every((c, i) => c.id === b[i]?.id && c.size === b[i]?.size)

/**
 * The signed-in user's dashboard layout (`/api/settings/dashboard`), with an
 * edit draft. Nothing is saved until `save()`; `cancel()` drops the draft.
 */
export function useDashboardLayout() {
  const { t } = useTranslation("dashboard")
  const [saved, setSaved] = React.useState<LayoutCard[] | null>(null)
  const [draft, setDraft] = React.useState<LayoutCard[] | null>(null)
  const [saving, setSaving] = React.useState(false)

  React.useEffect(() => {
    void api.GET("/api/settings/dashboard").then(({ data }) => {
      // On error, fall back to the default instead of an empty page.
      setSaved(known(data?.cards ?? DEFAULT_LAYOUT))
    })
  }, [])

  const editing = draft !== null
  const cards = draft ?? saved

  const begin = () => setDraft(saved ?? DEFAULT_LAYOUT)
  const cancel = () => setDraft(null)
  const reset = () => setDraft(DEFAULT_LAYOUT)

  async function save() {
    if (!draft) return
    if (saved && sameLayout(draft, saved)) {
      setDraft(null)
      return
    }
    setSaving(true)
    // The default is stored as null, so a user on the default gets new cards
    // added to it later.
    const body = { cards: sameLayout(draft, DEFAULT_LAYOUT) ? null : draft }
    const { error } = await api.PUT("/api/settings/dashboard", { body })
    setSaving(false)
    if (error) {
      toast.add({
        type: "error",
        title: t("layout.saveFailed"),
        description: errorMessage(error),
      })
      return // keep the draft so nothing is lost; the user can retry or cancel
    }
    setSaved(draft)
    setDraft(null)
    toast.add({ type: "success", title: t("layout.saved") })
  }

  return {
    cards,
    editing,
    saving,
    begin,
    cancel,
    reset,
    save,
    setDraft: (next: LayoutCard[]) => setDraft(next),
  }
}
