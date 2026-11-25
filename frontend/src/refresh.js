import { useEffect, useReducer } from 'react'

export const DATA_CHANGED_EVENT = 'sortbay:data-changed'

export function emitDataChanged(detail = {}) {
  window.dispatchEvent(new CustomEvent(DATA_CHANGED_EVENT, { detail }))
}

export function useDataChanged(load) {
  const [tick, bump] = useReducer((x) => x + 1, 0)

  useEffect(() => {
    const listener = () => bump()
    window.addEventListener(DATA_CHANGED_EVENT, listener)
    return () => window.removeEventListener(DATA_CHANGED_EVENT, listener)
  }, [])

  useEffect(() => {
    if (load) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick])

  return tick
}
