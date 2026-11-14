import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { pageFromPath, pathOf, usePage } from './page'

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

describe('pageFromPath', () => {
  it('maps paths to pages', () => {
    expect(pageFromPath('/')).toBe('puzzles')
    expect(pageFromPath('/progress')).toBe('progress')
    expect(pageFromPath('/progress/')).toBe('progress')
    expect(pageFromPath('/elsewhere')).toBe('puzzles')
  })

  it('round-trips with pathOf', () => {
    expect(pathOf('puzzles')).toBe('/')
    expect(pathOf('progress')).toBe('/progress')
  })
})

describe('usePage', () => {
  it('starts from the URL', () => {
    window.history.replaceState(null, '', '/progress')
    const { result } = renderHook(() => usePage())
    expect(result.current[0]).toBe('progress')
  })

  it('navigates with pushState and follows popstate', () => {
    const { result } = renderHook(() => usePage())
    act(() => result.current[1]('progress'))
    expect(window.location.pathname).toBe('/progress')
    expect(result.current[0]).toBe('progress')
    const length = window.history.length
    act(() => result.current[1]('progress'))
    expect(window.history.length).toBe(length)
    act(() => {
      window.history.replaceState(null, '', '/')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(result.current[0]).toBe('puzzles')
  })
})
