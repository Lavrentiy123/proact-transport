import { useCallback, useRef, useState } from 'react'
import type { ActionOutcome } from '../components/IncidentCard'
import type { Alert } from '../types/contracts'
import { isTimeout, postAction } from './liveTransport'

export type DispatcherAction = 'apply' | 'dismiss'

/** Dispatcher decisions per vehicle: POST /api/v1/actions in live, an emulated driver reply in the demo. */
export function useDispatcherActions(source: 'demo' | 'live') {
  const [outcomes, setOutcomes] = useState<Record<number, ActionOutcome>>({})
  // Responses to dispatcher actions from a previous source or replay session are dropped.
  const sessionRef = useRef(0)

  const reset = useCallback(() => {
    sessionRef.current += 1
    setOutcomes({})
  }, [])

  const act = useCallback(async (target: Alert, action: DispatcherAction) => {
    const session = sessionRef.current
    if (source === 'demo') {
      const outcome: ActionOutcome = {
        alert_id: target.alert_id,
        status: action === 'apply' ? 'applied' : 'dismissed',
        driver_message: action === 'apply'
          ? `Диспетчер: ${target.recommendation?.text ?? `${target.title}. Сообщите обстановку.`}`
          : 'Алерт отклонён диспетчером',
        driver_reply: action === 'apply' ? 'успеваю' : null,
      }
      setOutcomes((current) => ({ ...current, [target.tr_id]: outcome }))
      return
    }
    try {
      const response = await postAction(target.alert_id, action)
      if (session !== sessionRef.current) return
      setOutcomes((current) => ({ ...current, [target.tr_id]: response }))
    } catch (error: unknown) {
      if (session !== sessionRef.current) return
      const message = isTimeout(error) ? 'нет ответа 8 секунд'
        : error instanceof Error ? error.message : 'ошибка сети'
      setOutcomes((current) => ({ ...current, [target.tr_id]: { alert_id: target.alert_id, error: message } }))
    }
  }, [source])

  return { outcomes, act, reset }
}
