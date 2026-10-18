import { useCallback, useEffect, useRef, useState } from "react"
import { getResearchStatus, getSession, postChatStream } from "../api/client"
import type { ChatData, ChatMessage, ResearchStatus } from "../types"

const SESSION_STORAGE_KEY = "travel-agent:session-id"

function getOrCreateSessionId(): string {
  const existing = localStorage.getItem(SESSION_STORAGE_KEY)
  if (existing) return existing
  const fresh = crypto.randomUUID()
  localStorage.setItem(SESSION_STORAGE_KEY, fresh)
  return fresh
}

function newSessionId(): string {
  const fresh = crypto.randomUUID()
  localStorage.setItem(SESSION_STORAGE_KEY, fresh)
  return fresh
}

// `planning` is retained as a compatibility fallback for sessions created
// by an older backend that returned the stale pre-expansion state. New
// servers return `researching` for every background research pause.
const RESEARCHING_STAGES = new Set(["research", "researching", "planning"])

export function useChatSession() {
  const [sessionId, setSessionId] = useState(getOrCreateSessionId)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [data, setData] = useState<ChatData>({})
  const [researchStatus, setResearchStatus] = useState<ResearchStatus | null>(null)
  const [isBusy, setIsBusy] = useState(false)
  const pollTimer = useRef<number | undefined>(undefined)

  const resetSession = useCallback(() => {
    setSessionId(newSessionId())
    setMessages([])
    setData({})
    setResearchStatus(null)
  }, [])

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || isBusy) return
      setIsBusy(true)

      const userMsgId = crypto.randomUUID()
      const assistantMsgId = crypto.randomUUID()
      setMessages((prev) => [
        ...prev,
        { id: userMsgId, role: "user", content: trimmed },
        { id: assistantMsgId, role: "assistant", content: "", streaming: true },
      ])

      try {
        const finalEvent = await postChatStream(sessionId, trimmed, (token) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantMsgId ? { ...m, content: m.content + token } : m)),
          )
        })
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: finalEvent.response || m.content, streaming: false }
              : m,
          ),
        )
        if (finalEvent.data) setData(finalEvent.data)
      } catch (err) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: `出错了：${err instanceof Error ? err.message : String(err)}`, streaming: false }
              : m,
          ),
        )
      } finally {
        setIsBusy(false)
      }
    },
    [sessionId, isBusy],
  )

  // While the backend is running a research background job, poll for
  // per-worker progress and, once done, fetch the resulting state + append
  // the follow-up message (candidates/itinerary) that the background job
  // produced -- see travel_agent/execution/research_jobs.py.
  useEffect(() => {
    const stage = data.stage
    if (!stage || !RESEARCHING_STAGES.has(stage)) {
      setResearchStatus(null)
      return
    }

    let cancelled = false

    const poll = async () => {
      try {
        const status = await getResearchStatus(sessionId)
        if (cancelled) return
        setResearchStatus(status)

        if (status.status === "done" || status.status === "error") {
          const session = await getSession(sessionId)
          if (cancelled) return
          setData(session.data)
          if (session.response) {
            setMessages((prev) => [
              ...prev,
              { id: crypto.randomUUID(), role: "assistant", content: session.response },
            ])
          }
          return
        }
        pollTimer.current = window.setTimeout(poll, 1000)
      } catch {
        if (!cancelled) pollTimer.current = window.setTimeout(poll, 2000)
      }
    }

    poll()
    return () => {
      cancelled = true
      window.clearTimeout(pollTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.stage, sessionId])

  return { sessionId, messages, data, researchStatus, isBusy, sendMessage, resetSession }
}
