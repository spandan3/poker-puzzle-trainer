// The two pages, switched by the URL (`/` and `/progress`) with the History API: no router library.
import type { MouseEvent } from 'react'
import { useCallback, useEffect, useState } from 'react'

export type Page = 'puzzles' | 'progress'

export function pageFromPath(path: string): Page {
  const clean = path.replace(/\/+$/, '')
  return clean === '/progress' ? 'progress' : 'puzzles'
}

export function pathOf(page: Page): string {
  return page === 'progress' ? '/progress' : '/'
}

/** The current page, and a function that switches to another (a new history entry). */
export function usePage(): [Page, (page: Page) => void] {
  const [page, setPage] = useState<Page>(() => pageFromPath(window.location.pathname))

  useEffect(() => {
    const onPop = () => setPage(pageFromPath(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((next: Page) => {
    if (pageFromPath(window.location.pathname) !== next) {
      window.history.pushState(null, '', pathOf(next))
    }
    setPage(next)
  }, [])

  return [page, navigate]
}

/** A plain left click: the only kind a link hands to the app (Ctrl, Meta, Shift, Alt and middle clicks stay the browser's). */
export function isPlainLeftClick(e: MouseEvent): boolean {
  return (
    !e.defaultPrevented && e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey
  )
}
