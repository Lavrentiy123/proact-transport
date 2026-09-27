import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  try { window.localStorage.clear() } catch { /* storage may be unavailable */ }
})
