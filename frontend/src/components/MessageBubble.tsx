import type { ChatMessage } from "../types"

export default function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user"
  return (
    <div className={`flex animate-fade-in-up ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={
          "max-w-[80%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap " +
          (isUser
            ? "bg-[var(--accent)] text-white rounded-br-sm"
            : "border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] rounded-bl-sm")
        }
      >
        {message.content || (message.streaming ? " " : "")}
        {message.streaming && (
          <span className="ml-1 inline-flex gap-0.5 align-middle">
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current" style={{ animationDelay: "0ms" }} />
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current" style={{ animationDelay: "150ms" }} />
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current" style={{ animationDelay: "300ms" }} />
          </span>
        )}
      </div>
    </div>
  )
}
