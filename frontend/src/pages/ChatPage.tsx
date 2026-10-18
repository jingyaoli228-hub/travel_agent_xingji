import { useEffect, useRef } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useChatSession } from "../hooks/useChatSession"
import MessageBubble from "../components/MessageBubble"
import ChatInput from "../components/ChatInput"
import RequirementStatusCard from "../components/RequirementStatusCard"
import ResearchProgressPanel from "../components/ResearchProgressPanel"
import CandidatesPanel from "../components/CandidatesPanel"
import { FinalPlanSummary, ItineraryDays } from "../components/ItineraryView"
import { PlanningWorkspace } from "../components/PlanningWorkspace"

export default function ChatPage() {
  const { sessionId, messages, data, researchStatus, isBusy, sendMessage, resetSession } = useChatSession()
  const navigate = useNavigate()
  const location = useLocation()
  const scrollRef = useRef<HTMLDivElement>(null)
  const sentInitial = useRef(false)

  useEffect(() => {
    const initial = (location.state as { initialMessage?: string } | null)?.initialMessage
    if (initial && !sentInitial.current && messages.length === 0) {
      sentInitial.current = true
      sendMessage(initial)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages])

  const stage = data.stage
  const workspaceDays = data.final_plan?.itinerary.days || data.itinerary?.days

  return (
    <div className="flex h-screen flex-col bg-[var(--canvas)]">
      <header className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-2 text-sm font-semibold text-[var(--text)]"
        >
          <span className="grid h-6 w-6 place-items-center rounded-md bg-[var(--accent)] text-white">✈</span>
          AI Travel Planner
        </button>
        <button
          onClick={resetSession}
          className="rounded-full border border-[var(--border)] px-3 py-1 text-xs text-[var(--text-muted)] transition hover:border-[var(--accent)] hover:text-[var(--text)]"
        >
          新对话
        </button>
      </header>

      {workspaceDays?.length ? <PlanningWorkspace tripId={sessionId} initialDays={workspaceDays} messages={messages} isBusy={isBusy} onSend={sendMessage} /> : <div className="grid flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[1fr_380px]">
        <div className="flex min-h-0 flex-col">
          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.length === 0 && (
              <div className="mx-auto max-w-md pt-16 text-center text-sm text-[var(--text-muted)]">
                告诉我你想去哪里、什么时候去、和谁一起、预算多少，我会帮你规划完整行程。
              </div>
            )}
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
          </div>
          <ChatInput onSend={sendMessage} disabled={isBusy} />
        </div>

        <aside className="hidden min-h-0 space-y-4 overflow-y-auto border-l border-[var(--border)] bg-[var(--canvas)] p-4 lg:block">
          <RequirementStatusCard data={data} />
          <ResearchProgressPanel status={researchStatus} />
          {stage === "selection" && data.candidates && <CandidatesPanel candidates={data.candidates} />}
          {data.final_plan && <FinalPlanSummary plan={data.final_plan} />}
          {!data.final_plan && data.itinerary && data.itinerary.days.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-[var(--text)]">行程草案</h3>
              <ItineraryDays days={data.itinerary.days} />
            </div>
          )}
          {data.review_report && (
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 text-sm shadow-sm">
              <span className="font-semibold text-[var(--text)]">审核评分：</span>
              <span className="text-[var(--accent)]">{String(data.review_report.score)} / 100</span>
            </div>
          )}
          <div className="pb-2 text-center text-[11px] text-[var(--text-muted)]">会话 ID: {sessionId.slice(0, 8)}</div>
        </aside>
      </div>}
    </div>
  )
}
