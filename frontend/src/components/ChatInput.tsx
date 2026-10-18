import { useState } from "react"

export default function ChatInput({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void
  disabled: boolean
}) {
  const [value, setValue] = useState("")

  const submit = () => {
    if (!value.trim() || disabled) return
    onSend(value)
    setValue("")
  }

  return (
    <div className="flex items-end gap-2 border-t border-[var(--border)] bg-[var(--surface)] p-3">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        rows={1}
        placeholder={disabled ? "请稍候…" : "输入消息，Enter 发送，Shift+Enter 换行"}
        disabled={disabled}
        className="max-h-32 flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--canvas)] px-3 py-2.5 text-[15px] text-[var(--text)] outline-none placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] disabled:opacity-60"
      />
      <button
        onClick={submit}
        disabled={disabled || !value.trim()}
        className="shrink-0 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-40"
      >
        发送
      </button>
    </div>
  )
}
