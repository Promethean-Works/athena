"use client"

import * as React from "react"

/**
 * A ref that always holds the latest `value`, for callbacks and effects that
 * must not re-run when it changes (e.g. an inline `onChange` prop). It is
 * updated after render, so read it from handlers and effects, never while
 * rendering.
 */
export function useLatest<T>(value: T) {
  const ref = React.useRef(value)
  React.useLayoutEffect(() => {
    ref.current = value
  })
  return ref
}
