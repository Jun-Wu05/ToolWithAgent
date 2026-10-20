import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

export type PanelState = null | { type: 'execution' | 'artifact'; id: string }
type Tone = 'info' | 'success' | 'warning' | 'danger' | 'faint' | 'neutral'
const statuses: Record<string, { label: string; tone: Tone }> = {
  queued: { label: '排队中', tone: 'faint' }, pending: { label: '排队中', tone: 'faint' },
  running: { label: '运行中', tone: 'info' }, cancelling: { label: '取消中', tone: 'info' },
  waiting_confirmation: { label: '等待确认', tone: 'warning' },
  succeeded: { label: '已完成', tone: 'success' }, completed: { label: '已完成', tone: 'success' },
  failed: { label: '失败', tone: 'danger' }, cancelled: { label: '已取消', tone: 'neutral' },
}
const statusInfo = (status: string) => Object.hasOwn(statuses, status) ? statuses[status] : { label: '未知状态', tone: 'neutral' as const }

export function StatusDot({ status }: { status: string }) {
  return <span className={'status-dot tone-' + statusInfo(status).tone} aria-hidden="true" />
}

export function StatusText({ status, label, className = '' }: { status: string; label?: string; className?: string }) {
  return <span className={'status-text tone-' + statusInfo(status).tone + ' ' + className}><StatusDot status={status} /><span>{label || statusInfo(status).label}</span></span>
}

export function TaskHintBar({ state, status, title, description, children }: {
  state: 'running' | 'waiting_confirmation' | 'failed' | null
  status?: string; title: string; description?: string; children?: ReactNode
}) {
  if (!state) return null
  return <section className={'task-hint-bar hint-' + state} aria-label="当前任务提示" role="status">
    <StatusText status={status || state} /><strong>{title}</strong>{description && <span className="task-hint-description">{description}</span>}
    {children && <div className="task-hint-actions">{children}</div>}
  </section>
}

export function fmtMs(value?: number | null) {
  if (value == null || !Number.isFinite(value) || value < 0) return '—'
  if (value < 1000) return Math.round(value) + ' ms'
  if (value < 60000) return (value / 1000).toFixed(1) + ' 秒'
  return Math.floor(value / 60000) + ' 分 ' + Math.floor(value / 1000) % 60 + ' 秒'
}

export function fmtTokens(value?: number | null) {
  if (value == null || !Number.isFinite(value) || value < 0) return '—'
  return value >= 1000 ? (value / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(Math.round(value))
}

export function ToolCallBlock({ name, status, input, output, durationMs, tokens }: {
  name: string; status: string; input: string; output: string; durationMs?: number | null; tokens?: number | null
}) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return <section className="tool-call-block">
    <button type="button" className="tool-call-summary focus-ring" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
      <span aria-hidden="true">{open ? '▾' : '▸'}</span><StatusText status={status} /><code>{name}</code>
      <span className="num tool-call-metrics">{fmtMs(durationMs)} · {fmtTokens(tokens)} Token</span>
    </button>
    <div id={id} className="tool-call-content" hidden={!open}>{open && <><h4>输入</h4><pre>{input}</pre><h4>输出</h4><pre>{output}</pre></>}</div>
  </section>
}

type ContextTab = { id: string; label: string; content: ReactNode }
export function ContextPanel({ panel, title, onClose, tabs, durationMs, tokens }: {
  panel: PanelState; title: string; onClose: () => void; tabs: readonly ContextTab[]; durationMs?: number; tokens?: number
}) {
  const [selected, setSelected] = useState(tabs[0]?.id || '')
  const closeButton = useRef<HTMLButtonElement>(null)
  const tabButtons = useRef<(HTMLButtonElement | null)[]>([])
  const id = useId()
  const panelKey = panel ? panel.type + ':' + panel.id : ''
  useEffect(() => {
    if (!panelKey) return
    const previous = document.activeElement as HTMLElement | null
    closeButton.current?.focus()
    return () => { if (previous?.isConnected) previous.focus() }
  }, [panelKey])
  if (!panel) return null
  const label = panel.type === 'execution' ? '执行详情' : '产物详情'
  const current = tabs.find(tab => tab.id === selected)?.id || tabs[0]?.id
  return <aside className="context-panel" aria-label={label} onKeyDown={event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose() }
  }}>
    <header><div><h2>{title}</h2>{(durationMs != null || tokens != null) && <small className="num">{fmtMs(durationMs)} · {fmtTokens(tokens)} Token</small>}</div><button type="button" ref={closeButton} className="icon-button" aria-label={'关闭' + label} onClick={onClose}>关闭</button></header>
    <div className="context-tabs" role="tablist" aria-label={label + '分类'}>{tabs.map((tab, index) => <button type="button" key={tab.id} ref={element => { tabButtons.current[index] = element }} className="focus-ring" role="tab" id={id + '-tab-' + index} aria-selected={current === tab.id} aria-controls={id + '-pane-' + index} tabIndex={current === tab.id ? 0 : -1} onClick={() => setSelected(tab.id)} onKeyDown={event => {
      let next = index
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
      else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length
      else if (event.key === 'Home') next = 0
      else if (event.key === 'End') next = tabs.length - 1
      else return
      event.preventDefault(); setSelected(tabs[next].id); tabButtons.current[next]?.focus()
    }}>{tab.label}</button>)}</div>
    <div className="context-content">{tabs.map((tab, index) => <section key={tab.id} id={id + '-pane-' + index} role="tabpanel" aria-labelledby={id + '-tab-' + index} hidden={current !== tab.id}>{tab.content}</section>)}</div>
  </aside>
}
