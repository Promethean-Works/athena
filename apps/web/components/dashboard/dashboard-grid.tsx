"use client"

import * as React from "react"
import { useTranslation } from "react-i18next"
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
} from "@dnd-kit/core"
import {
  arrayMove,
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import {
  ArrowDownIcon,
  ArrowUpIcon,
  GripVerticalIcon,
  LayoutDashboardIcon,
  Maximize2Icon,
  Minimize2Icon,
  PlusIcon,
  RotateCcwIcon,
  XIcon,
} from "lucide-react"

import { Button } from "@workspace/ui/components/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@workspace/ui/components/dialog"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@workspace/ui/components/empty"
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@workspace/ui/components/item"
import { Skeleton } from "@workspace/ui/components/skeleton"
import { Spinner } from "@workspace/ui/components/spinner"
import { cn } from "@workspace/ui/lib/utils"

import { useAuth } from "@/components/auth-provider"
import { isAllowed, useCapabilities } from "@/components/capabilities-provider"
import {
  CARDS_BY_ID,
  DASHBOARD_CARDS,
  type DashboardCardDef,
  type LayoutCard,
} from "@/components/dashboard/cards"
import i18n from "@/lib/i18n"
import { useDashboardLayout } from "@/components/dashboard/use-dashboard-layout"

function subscribeReducedMotion(onChange: () => void) {
  const media = window.matchMedia("(prefers-reduced-motion: reduce)")
  media.addEventListener("change", onChange)
  return () => media.removeEventListener("change", onChange)
}

function useReducedMotion() {
  return React.useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => true
  )
}

const titleOf = (id: string | number) => {
  const def = CARDS_BY_ID.get(String(id))
  return def ? i18n.t(def.titleKey, { ns: "dashboard" }) : String(id)
}

/** What screen readers hear while a card is moved with the keyboard or pointer. */
const announcements: Announcements = {
  onDragStart: ({ active }) =>
    i18n.t("dashboard:grid.pickedUp", { title: titleOf(active.id) }),
  onDragOver: ({ active, over }) =>
    over
      ? i18n.t("dashboard:grid.overCard", {
          title: titleOf(active.id),
          other: titleOf(over.id),
        })
      : i18n.t("dashboard:grid.notOverCard", { title: titleOf(active.id) }),
  onDragEnd: ({ active, over }) =>
    over
      ? i18n.t("dashboard:grid.moved", {
          title: titleOf(active.id),
          other: titleOf(over.id),
        })
      : i18n.t("dashboard:grid.dropped", { title: titleOf(active.id) }),
  onDragCancel: ({ active }) =>
    i18n.t("dashboard:grid.cancelled", { title: titleOf(active.id) }),
}

function SortableCell({
  card,
  def,
  index,
  count,
  editing,
  reducedMotion,
  onMove,
  onResize,
  onRemove,
}: {
  card: LayoutCard
  def: DashboardCardDef
  index: number
  count: number
  editing: boolean
  reducedMotion: boolean
  onMove: (from: number, to: number) => void
  onResize: () => void
  onRemove: () => void
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: card.id, disabled: !editing })
  const { t } = useTranslation("dashboard")
  const title = t(def.titleKey)

  const full = card.size === "full"
  return (
    <div
      ref={setNodeRef}
      style={{
        // Translate only: scaling would squash a half card dragged over a full one.
        transform: CSS.Translate.toString(transform),
        transition: reducedMotion ? undefined : transition,
      }}
      className={cn(
        // Each cell is the container the card's own container queries measure,
        // so a half-width System card lays out for half the width.
        "@container/main min-w-0",
        // Cards side by side share a row's height.
        "[&>[data-slot=card]]:h-full",
        full && "xl:col-span-2",
        editing
          ? "flex flex-col gap-2 rounded-xl p-2 outline-2 outline-border outline-dashed"
          : "empty:hidden",
        isDragging && "relative z-10 opacity-80"
      )}
    >
      {editing ? (
        <>
          <div className="flex items-center gap-1">
            <Button
              ref={setActivatorNodeRef}
              variant="ghost"
              size="icon-sm"
              className="cursor-grab touch-none active:cursor-grabbing"
              aria-label={t("grid.move", { title })}
              {...attributes}
              {...listeners}
            >
              <GripVerticalIcon />
            </Button>
            <span className="flex-1 truncate text-sm font-medium">
              {title}
            </span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("grid.moveUp", { title })}
              disabled={index === 0}
              onClick={() => onMove(index, index - 1)}
            >
              <ArrowUpIcon />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("grid.moveDown", { title })}
              disabled={index === count - 1}
              onClick={() => onMove(index, index + 1)}
            >
              <ArrowDownIcon />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              // Sizes only differ where the grid has two columns.
              className="hidden xl:inline-flex"
              aria-label={
                full
                  ? t("grid.makeHalf", { title })
                  : t("grid.makeFull", { title })
              }
              onClick={onResize}
            >
              {full ? <Minimize2Icon /> : <Maximize2Icon />}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t("grid.remove", { title })}
              onClick={onRemove}
            >
              <XIcon />
            </Button>
          </div>
          {/* The card can't be used while arranging; it's only a preview. */}
          <div
            inert
            data-empty={t("grid.nothingToShow")}
            className="flex-1 [&>[data-slot=card]]:h-full empty:rounded-lg empty:border empty:border-dashed empty:p-4 empty:text-sm empty:text-muted-foreground empty:before:content-[attr(data-empty)]"
          >
            {def.render()}
          </div>
        </>
      ) : (
        def.render()
      )}
    </div>
  )
}

function AddCardDialog({
  open,
  onOpenChange,
  available,
  onAdd,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  available: DashboardCardDef[]
  onAdd: (def: DashboardCardDef) => void
}) {
  const { t } = useTranslation("dashboard")
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("grid.addDialogTitle")}</DialogTitle>
          <DialogDescription>{t("grid.addDialogDescription")}</DialogDescription>
        </DialogHeader>
        {available.length === 0 ? (
          <Empty className="border">
            <EmptyHeader>
              <EmptyTitle>{t("grid.allAddedTitle")}</EmptyTitle>
              <EmptyDescription>{t("grid.allAddedDescription")}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <ItemGroup className="max-h-[60vh] gap-2 overflow-y-auto">
            {available.map((def) => (
              <Item key={def.id} variant="outline" size="sm">
                <ItemMedia variant="icon">
                  <def.icon />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>{t(def.titleKey)}</ItemTitle>
                  <ItemDescription>{t(def.descriptionKey)}</ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={t("grid.addCard", { title: t(def.titleKey) })}
                    onClick={() => onAdd(def)}
                  >
                    <PlusIcon data-icon="inline-start" />
                    {t("grid.add")}
                  </Button>
                </ItemActions>
              </Item>
            ))}
          </ItemGroup>
        )}
      </DialogContent>
    </Dialog>
  )
}

/** The dashboard: the user's cards in their order, and edit mode to arrange them. */
export function DashboardGrid() {
  const { t } = useTranslation("dashboard")
  const layout = useDashboardLayout()
  const { manifest } = useCapabilities()
  const { user } = useAuth()
  const reducedMotion = useReducedMotion()
  const [adding, setAdding] = React.useState(false)

  const sensors = useSensors(
    // A small distance keeps clicks on the toolbar buttons from starting a drag.
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  const cards = layout.cards
  if (!cards) {
    return (
      <div className="grid gap-4 md:gap-6 xl:grid-cols-2">
        <Skeleton className="h-64 xl:col-span-2" />
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    )
  }

  const canShow = (def: DashboardCardDef) =>
    (!def.adminOnly || user.is_admin) &&
    (!def.capability ||
      !manifest ||
      isAllowed(manifest, def.capability, true))
  // The same rules as the picker: a non-admin never sees Recent activity, and
  // a card for something this host can't do doesn't render, even when it's in
  // the (default or saved) layout.
  const placed = cards.filter((c) => {
    const def = CARDS_BY_ID.get(c.id)
    return def !== undefined && canShow(def)
  })
  const available = DASHBOARD_CARDS.filter(
    (def) => !placed.some((c) => c.id === def.id) && canShow(def)
  )

  const update = (next: LayoutCard[]) => layout.setDraft(next)
  const move = (from: number, to: number) => {
    if (to < 0 || to >= placed.length) return
    update(arrayMove(placed, from, to))
  }
  function onDragEnd({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return
    const from = placed.findIndex((c) => c.id === active.id)
    const to = placed.findIndex((c) => c.id === over.id)
    if (from >= 0 && to >= 0) move(from, to)
  }

  return (
    <div className="flex flex-col gap-4 md:gap-6">
      {layout.editing ? (
        <div className="sticky top-2 z-20 flex flex-wrap items-center gap-2 rounded-xl border bg-background/95 p-2 pl-4 shadow-sm backdrop-blur">
          <p className="mr-auto text-sm text-muted-foreground">
            {t("grid.editHint")}
          </p>
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            <PlusIcon data-icon="inline-start" />
            {t("grid.addCardButton")}
          </Button>
          <Button variant="ghost" size="sm" onClick={layout.reset}>
            <RotateCcwIcon data-icon="inline-start" />
            {t("grid.reset")}
          </Button>
          <Button variant="ghost" size="sm" onClick={layout.cancel}>
            {t("grid.cancel")}
          </Button>
          <Button
            size="sm"
            onClick={() => void layout.save()}
            disabled={layout.saving}
          >
            {layout.saving ? <Spinner data-icon="inline-start" /> : null}
            {t("grid.done")}
          </Button>
        </div>
      ) : (
        <div className="-mb-2 flex justify-end md:-mb-4">
          <Button variant="ghost" size="sm" onClick={layout.begin}>
            <LayoutDashboardIcon data-icon="inline-start" />
            {t("grid.customize")}
          </Button>
        </div>
      )}

      {placed.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>{t("grid.emptyTitle")}</EmptyTitle>
            <EmptyDescription>{t("grid.emptyDescription")}</EmptyDescription>
          </EmptyHeader>
          {!layout.editing ? (
            <Button variant="outline" onClick={layout.begin}>
              {t("grid.customize")}
            </Button>
          ) : null}
        </Empty>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={onDragEnd}
          accessibility={{
            announcements,
            screenReaderInstructions: {
              draggable: t("grid.dragInstructions"),
            },
          }}
        >
          <SortableContext
            items={placed.map((c) => c.id)}
            strategy={rectSortingStrategy}
          >
            <div className="grid gap-4 md:gap-6 xl:grid-cols-2">
              {placed.map((card, index) => {
                const def = CARDS_BY_ID.get(card.id)
                if (!def) return null
                return (
                  <SortableCell
                    key={card.id}
                    card={card}
                    def={def}
                    index={index}
                    count={placed.length}
                    editing={layout.editing}
                    reducedMotion={reducedMotion}
                    onMove={move}
                    onResize={() =>
                      update(
                        placed.map((c) =>
                          c.id === card.id
                            ? { ...c, size: c.size === "full" ? "half" : "full" }
                            : c
                        )
                      )
                    }
                    onRemove={() =>
                      update(placed.filter((c) => c.id !== card.id))
                    }
                  />
                )
              })}
            </div>
          </SortableContext>
        </DndContext>
      )}

      <AddCardDialog
        open={adding}
        onOpenChange={setAdding}
        available={available}
        onAdd={(def) => {
          update([...placed, { id: def.id, size: def.defaultSize }])
          setAdding(false)
        }}
      />
    </div>
  )
}
