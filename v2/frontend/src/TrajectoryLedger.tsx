import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type Artifact, type Conversation, type DiagnosticRun, type Run, type RunEvent } from './api'
import { businessName, phaseName, pipelineStageName, pipelineErrorName } from './BusinessWorkspace'
import { StatusText } from './VisualPrimitives'

type Entry = { key: string; run: Run; event?: RunEvent; at: string; title: string; summary: string; status: string }
type Row = { kind: 'single'; run: Run; entry: Entry } | { kind: 'group'; run: Run; entry: Entry; members: RunEvent[] }
type Props = { conversation: Conversation; onOpen: (artifact: Artifact) => void; onDetails?: (id: string) => void; targetId?: string | null; targetToken?: number; onRetry?: (id: string) => void; onStop?: (id: string) => void; canOperate?: boolean; busy?: boolean }
const time = (at?: string) => at && Number.isFinite(Date.parse(at)) ? new Date(at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '时间未采集'
const eventName = (event: RunEvent) => {
  if (event.event_type === 'run_progress') {
    const done = event.summary?.progress_status === 'success'
    return ({ retrieval: done ? '检索完成' : '检索候选字段', model_call: done ? '模型调用完成' : '模型调用', validation: '验证映射', writeback: '写回结果', completed: '步骤完成' } as Record<string, string>)[event.summary?.phase || ''] || '步骤进展'
  }
  return ({ run_queued: '已排队', run_started: '开始执行', run_succeeded: '执行完成', run_failed: '执行失败', run_cancelled: '已取消' } as Record<string, string>)[event.event_type] || event.event_type.replaceAll('_', ' ')
}
const eventSummary = (event: RunEvent) => {
  const summary = event.summary || {}
  const pieces = [pipelineStageName[summary.pipeline_stage || ''] || phaseName[summary.phase || ''], summary.phase === 'execution' && summary.operation ? businessName(summary.operation) : undefined].filter(Boolean)
  if (summary.current_batch && summary.total_batches) pieces.push(`批次 ${summary.current_batch}/${summary.total_batches}`)
  if (summary.error_code) pieces.push(pipelineErrorName[summary.error_code] || summary.error_code)
  return [...new Set(pieces)].join(' · ') || '摘要未采集'
}
const runFinal = (run: Run) => ['succeeded', 'failed', 'cancelled'].includes(run.status) ? run.status : ''
// store 写 run_progress 时 status 硬编码 'running'；Run 已终态时历史事件由前端按终态回填，不改后端数据。
const eventStatus = (run: Run, event?: RunEvent) => {
  const progress = event?.summary?.progress_status
  if (progress === 'success') return 'succeeded'
  if (progress === 'failed') return 'failed'
  if (!event) return run.status
  return runFinal(run) || event.status
}
const makeEntry = (run: Run, event: RunEvent): Entry => ({ key: `${run.id}:${event.sequence}`, run, event, at: event.created_at || '', title: eventName(event), summary: eventSummary(event), status: eventStatus(run, event) })
const stepTitle = (event: RunEvent) => {
  const summary = event.summary || {}
  return pipelineStageName[summary.pipeline_stage || ''] || phaseName[summary.phase || ''] || (summary.operation ? businessName(summary.operation) : '执行步骤')
}
const scopeTypeName = (value?: string) => ({ run: '执行', step: '步骤' }[value || ''] || value || '未采集')
// 与 ConversationTimeline.dedupeStepLines 同键合并（scope_id + pipeline_stage）；少于 2 条不折叠。
const buildRows = (run: Run, events: RunEvent[]): Row[] => {
  const rows: Row[] = [{ kind: 'single', run, entry: { key: `${run.id}:run`, run, at: runAt(run), title: businessName(run.kind || run.type || ''), summary: `Run ${run.id.slice(0, 8)} · ${elapsed(run)}`, status: run.status } }]
  const pending = new Map<string, RunEvent[]>()
  for (const event of events) {
    if (event.event_type === 'run_progress' && event.scope_id) {
      const groupKey = event.scope_id + ':' + (event.summary?.pipeline_stage || '')
      const members = pending.get(groupKey)
      if (members) { members.push(event); continue }
      const fresh: RunEvent[] = [event]
      pending.set(groupKey, fresh)
      rows.push({ kind: 'group', run, entry: { ...makeEntry(run, event), key: `${run.id}:g:${event.sequence}` }, members: fresh })
      continue
    }
    rows.push({ kind: 'single', run, entry: makeEntry(run, event) })
  }
  return rows
}
const runAt = (run: Run) => run.queued_at || run.created_at || ''
const elapsed = (run: Run) => {
  if (!run.started_at || !run.finished_at) return '耗时未采集'
  const seconds = Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000)
  return seconds >= 0 ? seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒` : '耗时未采集'
}

export function TrajectoryLedger({ conversation, onOpen, onDetails, targetId, targetToken, onRetry, onStop, canOperate, busy }: Props) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [limit, setLimit] = useState(20)
  const [pinnedRunId, setPinnedRunId] = useState<string | null>(null)
  const [retryToken, setRetryToken] = useState(0)
  const requested = useRef(new Map<string, string>())
  const [details, setDetails] = useState<Record<string, Run>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [selected, setSelected] = useState<string | null>(null)
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})
  const [diagnostic, setDiagnostic] = useState<DiagnosticRun | null>(null)
  const [diagnosticError, setDiagnosticError] = useState('')
  const [diagnosticTarget, setDiagnosticTarget] = useState<string | null>(null)
  const [selectedCall, setSelectedCall] = useState<string | null>(null)
  const [callDetail, setCallDetail] = useState<DiagnosticRun['calls'][number] | null>(null)
  const [callTab, setCallTab] = useState<'summary' | 'request' | 'response'>('summary')
  const selectedRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const runs = useMemo(() => [...conversation.runs].sort((a, b) => runAt(a).localeCompare(runAt(b)) || a.id.localeCompare(b.id)), [conversation.runs])
  const visibleRuns = useMemo(() => {
    const recent = runs.slice(-limit).reverse()
    const target = runs.find(run => run.id === (pinnedRunId || targetId))
    return target && !recent.includes(target) ? [...recent, target].sort((a, b) => runAt(b).localeCompare(runAt(a)) || b.id.localeCompare(a.id)) : recent
  }, [runs, limit, targetId, pinnedRunId])

  useEffect(() => { requested.current.clear(); setDetails({}); setErrors({}); setSelected(null); setOpenGroups({}); setPinnedRunId(null); setLimit(20) }, [conversation.id])
  useEffect(() => {
    if (!visibleRuns.length) return
    let alive = true
    const missing = visibleRuns.filter(run => requested.current.get(run.id) !== (run.updated_at || run.status))
    if (!missing.length) return
    missing.forEach(run => requested.current.set(run.id, run.updated_at || run.status))
    // Four readers keep long histories responsive without flooding the API.
    let next = 0
    const worker = async () => {
      while (alive && next < missing.length) {
        const run = missing[next++]
        try { const value = await api.run(run.id); if (alive) setDetails(old => ({ ...old, [run.id]: value })) }
        catch (error) { if (alive) setErrors(old => ({ ...old, [run.id]: error instanceof Error ? error.message : '事件读取失败' })) }
      }
    }
    void Promise.all(Array.from({ length: Math.min(4, missing.length) }, worker))
    return () => { alive = false }
  }, [visibleRuns, retryToken])

  useEffect(() => {
    if (!targetId) return
    setQuery(''); setStatus(''); setSelected(`${targetId}:run`)
  }, [targetId, targetToken])
  useEffect(() => { setSelectedCall(null); setCallDetail(null); setCallTab('summary') }, [selected])
  const selectedRunId = selected?.split(':')[0]
  useEffect(() => { setDiagnostic(null); setDiagnosticError(''); setSelectedCall(null); setCallDetail(null); setDiagnosticTarget(null) }, [selectedRunId])
  useEffect(() => {
    if (!diagnosticTarget) return
    let alive = true
    api.userDiagnosticRun(diagnosticTarget).then(value => { if (alive) setDiagnostic(value) }).catch(error => { if (alive) setDiagnosticError(error instanceof Error ? error.message : '诊断读取失败') })
    return () => { alive = false }
  }, [diagnosticTarget])
  useEffect(() => {
    if (!selectedRunId || !selectedCall || callTab === 'summary') return
    let alive = true
    setCallDetail(null)
    api.userDiagnosticCall(selectedRunId, selectedCall).then(value => { if (alive) setCallDetail(value) }).catch(() => { if (alive) setCallDetail(null) })
    return () => { alive = false }
  }, [selectedRunId, selectedCall, callTab])

  const items = useMemo(() => visibleRuns.flatMap(run => buildRows(run, details[run.id]?.events || [])), [visibleRuns, details])
  const entries = useMemo(() => items.flatMap(item => item.kind === 'group' ? item.members.map(event => makeEntry(item.run, event)) : [item.entry]), [items])
  useEffect(() => {
    const row = selectedRef.current, list = listRef.current
    if (!row || !list) return
    const item = row.getBoundingClientRect(), viewport = list.getBoundingClientRect()
    if (item.top < viewport.top || item.bottom > viewport.bottom) {
      list.scrollTop += item.top - viewport.top - (viewport.height - item.height) / 2
    }
  }, [selected, entries.length])
  const search = query.trim().toLocaleLowerCase()
  const filtering = !!(search || status)
  const entryMatches = (entry: Entry) => (!status || entry.status === status) && (!search || `${entry.title} ${entry.summary} ${entry.run.id} ${entry.event?.scope_id || ''}`.toLocaleLowerCase().includes(search))
  const filtered = items.flatMap((item): Row[] => {
    if (item.kind === 'single') return entryMatches(item.entry) ? [item] : []
    const members = item.members.filter(event => entryMatches(makeEntry(item.run, event)))
    return members.length ? [{ kind: 'group', run: item.run, entry: item.entry, members }] : []
  })
  const renderEntry = (entry: Entry) => <button type="button" aria-label={entry.event ? `查看事件 ${entry.title}` : '执行详情'} ref={entry.key === selected ? selectedRef : undefined} className={'trajectory-entry' + (entry.event ? ' trajectory-event' : ' trajectory-run') + (selected === entry.key ? ' selected' : '')} aria-current={selected === entry.key ? 'true' : undefined} onClick={() => setSelected(entry.key)}><time>{time(entry.at)}</time><span className="trajectory-rail" aria-hidden="true" /><span className="trajectory-copy"><strong>{entry.title}</strong><span>{entry.summary}</span></span><StatusText status={entry.status} /></button>
  const chosen = entries.find(entry => entry.key === selected)
  const artifactList = (conversation.artifacts || []).filter(item => item.run_id === selectedRunId)
  const messageById = new Map(conversation.messages.map(message => [message.id, message]))
  const firstTime = runs.length ? Date.parse(runAt(runs[0])) : NaN
  const min = Number.isFinite(firstTime) ? firstTime : 0
  const max = Math.max(...runs.map(run => Date.parse(run.finished_at || run.started_at || runAt(run))).filter(Number.isFinite), min + 1000)
  const span = max - min || 1000
  return <section className="trajectory" aria-label="执行轨迹" onKeyDown={event => { if (event.key === 'Escape' && selected) { setSelected(null); event.stopPropagation() } }}>
    {conversation.files.length > 0 && <div className="trajectory-inputs">输入文件 · <ul>{conversation.files.map(file => <li key={file.id}><span>{file.name}</span>{file.active === false && <small> · 历史输入</small>}</li>)}</ul></div>}
    <header className="trajectory-heading"><div><h2>执行轨迹</h2><p>{runs.length} 次执行 · {entries.length - visibleRuns.length} 条已记录事件 · 独立工具事件未采集{visibleRuns.length < runs.length && ' · 继续载入可查看更早记录'}</p></div><div className="trajectory-tools"><input aria-label="搜索轨迹" placeholder="搜索步骤、状态或 Run ID" value={query} onChange={event => setQuery(event.target.value)} /><select aria-label="筛选轨迹状态" value={status} onChange={event => setStatus(event.target.value)}><option value="">全部状态</option><option value="failed">失败</option><option value="waiting_confirmation">待确认</option><option value="running">运行中</option><option value="succeeded">完成</option></select></div></header>
    <nav className="trajectory-timeband" aria-label="运行时间导航"><div className="trajectory-timeband-label"><span>{time(runs[0] && runAt(runs[0]))}</span><div className="trajectory-timeband-legend" aria-label="时间条颜色图例"><span><span className="legend-swatch legend-done" aria-hidden="true" />已完成</span><span><span className="legend-swatch legend-live" aria-hidden="true" />进行中</span><span><span className="legend-swatch legend-failed" aria-hidden="true" />失败</span></div><span>{time(runs.at(-1)?.finished_at || (runs.at(-1) && runAt(runs.at(-1)!)))}</span></div><div className="trajectory-timeband-track">{runs.map(run => { const start = Date.parse(runAt(run)); const finish = Date.parse(run.finished_at || run.started_at || runAt(run)); const left = Number.isFinite(start) ? Math.max(0, (start - min) / span * 100) : 0; const width = Number.isFinite(start) && Number.isFinite(finish) ? Math.max(0.7, (finish - start) / span * 100) : 0.7; return <button key={run.id} style={{ left: `${left}%`, width: `${width}%` }} className={'trajectory-time-mark ' + run.status} aria-label={`定位 ${businessName(run.kind || run.type || '')} ${run.id.slice(0, 8)}`} title={`${time(runAt(run))} ${businessName(run.kind || run.type || '')}`} onClick={() => { setQuery(''); setStatus(''); setPinnedRunId(run.id); setSelected(`${run.id}:run`) }} /> })}</div></nav>
    <div className={'trajectory-columns' + (chosen ? ' has-inspector' : '')}><div ref={listRef} className="trajectory-list" role="list" aria-label="事件账本">{filtered.map((item, index) => { const prior = filtered[index - 1]; const showGroup = item.run.message_id && (prior?.run.message_id !== item.run.message_id); const message = item.run.message_id ? messageById.get(item.run.message_id) : undefined; const grouped = item.kind === 'group' && item.members.length > 1; const latest = grouped ? item.members[item.members.length - 1] : null; const open = grouped && (filtering || !!openGroups[item.entry.key]); return <div role="listitem" key={item.entry.key}>{showGroup && <div className="trajectory-group"><span>用户输入</span><strong>{message?.content || '关联消息内容未采集'}</strong></div>}{grouped && latest ? <><button type="button" aria-expanded={open} className={'trajectory-entry trajectory-event trajectory-step-group' + (open ? ' open' : '')} onClick={() => setOpenGroups(old => ({ ...old, [item.entry.key]: !old[item.entry.key] }))}><time>{time(latest.created_at || '')}</time><span className="trajectory-rail" aria-hidden="true" /><span className="trajectory-copy"><strong>{stepTitle(latest)}</strong><span>{businessName(latest.summary?.operation || '')} · {item.members.length} 条事件</span></span><span className="trajectory-group-toggle"><span aria-hidden="true">{open ? '▾' : '▸'}</span><StatusText status={eventStatus(item.run, latest)} /></span></button>{open && <div className="trajectory-step-members">{item.members.map(event => renderEntry(makeEntry(item.run, event)))}</div>}</> : renderEntry(item.kind === 'group' ? makeEntry(item.run, item.members[0]) : item.entry)}{!item.entry.event && errors[item.run.id] && <button className="trajectory-load-error" onClick={() => { requested.current.delete(item.run.id); setErrors(old => { const next = { ...old }; delete next[item.run.id]; return next }); setRetryToken(value => value + 1) }}>事件读取失败：{errors[item.run.id]} · 重试</button>}{!item.entry.event && !details[item.run.id] && !errors[item.run.id] && <div className="trajectory-loading" role="status">正在读取已记录事件…</div>}</div> })}{!filtered.length && <p className="workspace-empty">没有符合条件的事件。</p>}{visibleRuns.length < runs.length && <button className="trajectory-more button-secondary" onClick={() => setLimit(limit + 20)}>载入更多执行</button>}</div>
    {chosen && <aside className="trajectory-inspector" aria-label="选中事件详情"><header><div><small>{chosen.event ? `事件 ${chosen.event.sequence}` : '执行'}</small><h3>{chosen.title}</h3></div><button className="button-text" aria-label="关闭事件详情" onClick={() => setSelected(null)}>关闭</button></header><dl><dt>状态</dt><dd><StatusText status={chosen.status} /></dd><dt>时间</dt><dd>{time(chosen.at)}</dd><dt>Run</dt><dd><code>{chosen.run.id}</code></dd>{chosen.event && <><dt>层级</dt><dd>{scopeTypeName(chosen.event.scope_type)}</dd><dt>步骤</dt><dd><code>{chosen.event.scope_id || '未采集'}</code></dd></>}</dl><section><h4>记录摘要</h4><p>{chosen.summary}</p>{chosen.run.error_code && <p className="trajectory-error">{chosen.run.error_code}：{chosen.run.error_message || '原因未采集'}</p>}</section>{artifactList.length > 0 && <section><h4>关联产物</h4>{artifactList.map(item => <button className="button-text" key={item.id} onClick={() => onOpen(item)}>{businessName(item.kind)} · {item.id.slice(-8)}</button>)}</section>}{!diagnostic && <section><button className="button-secondary" onClick={() => setDiagnosticTarget(chosen.run.id)} disabled={!!diagnosticTarget}>查看模型调用</button>{diagnosticTarget && !diagnosticError && <p role="status">正在读取调用元数据…</p>}</section>}{diagnosticError && <p role="alert">{diagnosticError}</p>}{diagnostic && <section><h4>模型调用 · {diagnostic.calls.length}</h4>{diagnostic.calls.filter(call => !chosen.event || call.scope_id === chosen.event.scope_id).map(call => <button key={call.id} className="trajectory-call" onClick={() => { setSelectedCall(call.id); setCallTab('summary') }} aria-pressed={selectedCall === call.id}><strong>{call.operation || call.model || '调用'}</strong><small>{call.model} · {call.duration_ms == null ? '耗时未采集' : `${call.duration_ms} ms`}</small></button>)}{chosen.event && !diagnostic.calls.some(call => call.scope_id === chosen.event?.scope_id) && <p className="trajectory-uncollected">此步骤的调用关联未采集</p>}</section>}{selectedCall && diagnostic && <section><div className="trajectory-call-tabs" role="tablist" aria-label="调用内容">{(['summary', 'request', 'response'] as const).map(tab => <button key={tab} role="tab" aria-selected={callTab === tab} onClick={() => setCallTab(tab)}>{({ summary: '概览', request: '参数', response: '结果' })[tab]}</button>)}</div>{callTab === 'summary' ? <p>{diagnostic.calls.find(call => call.id === selectedCall)?.operation || '调用元数据'}</p> : <pre>{callDetail ? (callTab === 'request' ? callDetail.request : callDetail.response) || '未采集或无权限' : '正在按权限读取…'}</pre>}</section>}<footer><button className="button-secondary" aria-label="查看详细日志与模型调用" onClick={() => onDetails?.(chosen.run.id)}>完整诊断</button>{canOperate && ['failed', 'cancelled'].includes(chosen.run.status) && <button className="button-secondary" disabled={busy} onClick={() => onRetry?.(chosen.run.id)}>重新执行</button>}{canOperate && ['queued', 'running', 'waiting_confirmation'].includes(chosen.run.status) && <button className="button-secondary" disabled={busy} onClick={() => onStop?.(chosen.run.id)}>停止执行</button>}</footer></aside>}</div>
  </section>
}
