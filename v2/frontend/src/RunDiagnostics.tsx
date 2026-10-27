import { useEffect, useMemo, useState } from 'react'
import { api, saveDownload, type DiagnosticRun } from './api'

type Tab = '概览' | '执行时间线' | '输入与输出' | '日志' | '产物'
const tabs: Tab[] = ['概览', '执行时间线', '输入与输出', '日志', '产物']
const time = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '未采集'
const text = (value?: string | null) => value || '未采集'
const formatted = (value?: string) => {
  if (!value) return '未采集'
  try { return JSON.stringify(JSON.parse(value), null, 2) }
  catch { return value }
}
const nextAction = (status: string) => status === 'failed'
  ? '根据错误码与关联调用排查；证据不足时复现并重新采集。'
  : status === 'running' || status === 'queued' || status === 'waiting_confirmation'
    ? '执行尚未结束，请刷新查看最新证据。'
    : status === 'cancelled' ? '执行已取消，可查看已保留的历史证据。' : '无需处理。'

export function RunDiagnostics() {
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [list, setList] = useState<Awaited<ReturnType<typeof api.diagnosticRuns>> | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [detail, setDetail] = useState<DiagnosticRun | null>(null)
  const [tab, setTab] = useState<Tab>('概览')
  const [selectedCall, setSelectedCall] = useState<string | null>(null)
  const [callContent, setCallContent] = useState<DiagnosticRun['calls'][number] | null>(null)
  const [callLoading, setCallLoading] = useState(false)
  const [callError, setCallError] = useState('')
  const [selectedNode, setSelectedNode] = useState<number | null>(null)
  const [logLevel, setLogLevel] = useState('')
  const [logSource, setLogSource] = useState('')
  const [logScope, setLogScope] = useState('')
  const [logQuery, setLogQuery] = useState('')
  const [raw, setRaw] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    let live = true
    setError(''); setLoading(true)
    api.diagnosticRuns(status, page).then(value => { if (live) setList(value) })
      .catch(err => { if (live) setError(err instanceof Error ? err.message : '读取失败') })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [status, page, revision])
  useEffect(() => {
    if (!runId) { setDetail(null); return }
    let live = true
    setError(''); setLoading(true)
    api.diagnosticRun(runId).then(value => {
      if (!live) return
      setDetail(value)
      setSelectedCall((value.calls.find(call => call.error_code) || value.calls[0])?.id || null)
      setSelectedNode((value.timeline.find(node => node.status === 'failed' || node.summary.progress_status === 'failed') || value.timeline.at(-1))?.sequence || null)
      setTab('概览')
    }).catch(err => { if (live) setError(err instanceof Error ? err.message : '读取失败') })
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [runId, revision])
  useEffect(() => {
    setCallContent(null); setCallError('')
    if (!runId || !selectedCall || tab !== '输入与输出') return
    let live = true
    setCallLoading(true)
    api.diagnosticCall(runId, selectedCall).then(value => { if (live) setCallContent(value) })
      .catch(err => { if (live) setCallError(err instanceof Error ? err.message : '调用内容读取失败') })
      .finally(() => { if (live) setCallLoading(false) })
    return () => { live = false }
  }, [runId, selectedCall, tab, revision])
  const call = callContent?.id === selectedCall ? callContent : detail?.calls.find(item => item.id === selectedCall)
  const node = detail?.timeline.find(item => item.sequence === selectedNode)
  const planned = detail?.planned_steps || []
  const callsByScope = (scopeId: string) => detail?.calls.filter(item => item.scope_id === scopeId) || []
  const evidenceCallId = detail?.conclusion.call_id || detail?.conclusion.evidence_call_id
  const evidenceScopeId = detail?.conclusion.scope_id || detail?.conclusion.evidence_scope_id
  const logs = useMemo(() => (detail?.logs || []).filter(item =>
    (!logLevel || item.level === logLevel) && (!logSource || item.source === logSource) &&
    (!logScope || item.scope_id === logScope) &&
    (!logQuery || JSON.stringify(item).toLowerCase().includes(logQuery.toLowerCase()))
  ).sort((a, b) => (a.level === 'error' ? -1 : 0) - (b.level === 'error' ? -1 : 0)), [detail, logLevel, logSource, logScope, logQuery])
  const download = async () => {
    if (!runId) return
    try { saveDownload(await api.diagnosticBundle(runId)) }
    catch (err) { setError(err instanceof Error ? err.message : '下载失败') }
  }
  return <section className="activity-section run-diagnostics" aria-label="Run 诊断">
    <header className="diagnostic-header"><div><h2>Run 诊断</h2><p>按 Run 查看关联证据。旧 Run 的缺失数据标为「未采集」。</p></div><button className="button-secondary" onClick={() => setRevision(value => value + 1)} disabled={loading}>刷新</button></header>
    {error && <p role="alert" className="mapping-error">{error}</p>}
    {loading && <p role="status">正在读取诊断…</p>}
    {!runId && <>
      <div className="mapping-toolbar"><label>状态筛选<select aria-label="诊断状态筛选" value={status} onChange={event => { setStatus(event.target.value); setPage(1) }}><option value="">全部状态</option>{['queued', 'running', 'succeeded', 'failed', 'cancelled'].map(item => <option key={item} value={item}>{item}</option>)}</select></label></div>
      {list && <><div className="workbench-table-scroll"><table className="workbench-artifacts"><thead><tr><th>Run</th><th>所有者</th><th>任务</th><th>状态</th><th>更新时间</th></tr></thead><tbody>{list.items.map(item => <tr key={item.id}><td><button className="button-secondary" onClick={() => setRunId(item.id)}>{item.id.slice(-8)}</button></td><td>{item.owner_name}</td><td>{item.kind}</td><td>{item.status}</td><td>{time(item.updated_at)}</td></tr>)}</tbody></table></div>{!list.items.length && <p>暂无 Run。</p>}{list.total > list.page_size && <div className="mapping-pagination"><button disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><span>{page} / {Math.ceil(list.total / list.page_size)}</span><button disabled={page >= Math.ceil(list.total / list.page_size)} onClick={() => setPage(page + 1)}>下一页</button></div>}</>}
    </>}
    {runId && <><div className="diagnostic-header"><button className="button-secondary" onClick={() => setRunId(null)}>返回 Run 列表</button><span className="mono">{runId}</span><button className="button-secondary" onClick={() => void download()} disabled={!detail}>下载脱敏诊断包</button></div>
      {detail && <><nav className="diagnostic-tabs" aria-label="Run 详情" role="tablist">{tabs.map(item => <button key={item} role="tab" aria-selected={tab === item} className={tab === item ? 'selected' : ''} onClick={() => setTab(item)}>{item}</button>)}</nav>
        {tab === '概览' && <div role="tabpanel" className="diagnostic-summary"><h3>{detail.run.status === 'failed' ? '故障结论' : '执行摘要'}</h3><p><strong>{detail.run.status}</strong> · {detail.conclusion.category}{detail.conclusion.reason && ' · ' + detail.conclusion.reason}</p>{detail.conclusion.possible_cause && <p>可能原因：{detail.conclusion.possible_cause}（以失败调用为线索，尚未证明是 Run 的最终原因）</p>}<h3>影响范围</h3><p>{detail.run.owner_name} / {detail.run.conversation_title} · {detail.run.kind}</p><h3>关键证据</h3><p>模型调用：{detail.calls.length} · 时间线事件：{detail.timeline.length} · 产物：{detail.artifacts.length} · {detail.evidence_status}</p>{evidenceCallId && <button className="button-secondary" onClick={() => { setSelectedCall(evidenceCallId); setTab('输入与输出') }}>查看失败调用证据</button>}{evidenceScopeId && <button className="button-secondary" onClick={() => { setSelectedNode(detail.timeline.find(item => item.scope_id === evidenceScopeId)?.sequence || null); setTab('执行时间线') }}>查看执行节点</button>}<h3>建议处理</h3><p>{nextAction(detail.run.status)}</p></div>}
        {tab === '执行时间线' && <div role="tabpanel" className="diagnostic-split"><div className="diagnostic-list" aria-label="执行节点"><strong>Run / Task · {detail.run.id} / {detail.run.task_id}</strong>{planned.map(step => <div key={step.scope_id} className="diagnostic-step"><strong>Step · {step.operation || '未采集'} · {step.scope_id}</strong><small>依赖：{step.dependency_scope_ids.join('、') || '无'}</small>{detail.unexecuted_steps?.some(item => item.scope_id === step.scope_id) ? <span className="diagnostic-unexecuted">未执行 · {detail.unexecuted_steps.find(item => item.scope_id === step.scope_id)?.reason}</span> : detail.timeline.filter(item => item.scope_id === step.scope_id).map(item => <button key={item.sequence} onClick={() => setSelectedNode(item.sequence)}>{String(item.summary.progress_status || item.status)} · {time(item.created_at)}</button>)}{callsByScope(step.scope_id).map(item => <button key={item.id} onClick={() => { setSelectedCall(item.id); setTab('输入与输出') }}>模型调用 · {item.id}</button>)}</div>)}{!planned.length && detail.timeline.map(item => <button key={item.sequence} className={selectedNode === item.sequence ? 'selected' : ''} onClick={() => setSelectedNode(item.sequence)}><span>{item.scope_type} · {item.scope_id}</span><small>{item.event_type} · {String(item.summary.progress_status || item.status)} · {time(item.created_at)}</small></button>)}{!detail.timeline.length && <p>未采集</p>}{detail.run.status === 'failed' && !planned.length && <p className="diagnostic-unexecuted">未执行的下游节点未采集；不能从现有证据推断节点清单。</p>}</div><div className="diagnostic-detail">{node ? <><h3>{node.event_type}</h3><p>范围：{node.scope_type} / {node.scope_id}</p><p>状态：{String(node.summary.progress_status || node.status)} · {time(node.created_at)}</p><pre>{JSON.stringify(node.summary, null, 2)}</pre></> : <p>请选择节点</p>}</div></div>}
        {tab === '输入与输出' && <div role="tabpanel" className="diagnostic-split"><div className="diagnostic-list" aria-label="模型调用">{detail.calls.map(item => <button key={item.id} className={selectedCall === item.id ? 'selected' : ''} onClick={() => setSelectedCall(item.id)}><span>第 {item.attempt ?? '未采集'} 次 · {item.provider} / {item.model}</span><small>{item.error_code || '成功'} · {item.duration_ms ?? '未采集'} ms</small></button>)}{!detail.calls.length && <p>未采集</p>}</div><div className="diagnostic-detail">{call ? <><h3>调用详情</h3><dl><dt>Run / Task / Scope</dt><dd>{call.run_id} / {call.task_id} / {text(call.scope_id)}</dd><dt>操作 / Skill ID / Tool ID</dt><dd>{text(call.operation)} / 未采集 / 未采集</dd><dt>请求 ID</dt><dd>{text(call.request_id)}</dd><dt>Prompt / 标准字段表</dt><dd>{text(call.prompt_version)} / {text(call.standard_field_version)}</dd><dt>Provider 配置版本</dt><dd>{call.provider_config_revision ?? '未采集'}</dd><dt>参数</dt><dd>{JSON.stringify(call.params || {})}</dd><dt>输入产物版本</dt><dd>{call.input_artifact_id ? `${call.input_artifact_id} / v${call.input_artifact_version}` : '未采集'}</dd><dt>开始 / 结束</dt><dd>{time(call.started_at)} / {time(call.finished_at)}</dd><dt>错误码</dt><dd>{text(call.error_code)}</dd></dl><button className="button-secondary" onClick={() => setRaw(value => !value)}>{raw ? '格式化' : '原始 JSON'}</button>{callLoading && <p role="status">正在读取调用内容…</p>}{callError && <p role="alert">{callError}</p>}<h4>请求 {call.request_truncated && '（已截断）'}</h4><pre>{raw ? text(call.request) : formatted(call.request)}</pre><h4>响应 {call.response_truncated && '（已截断）'}</h4><pre>{raw ? text(call.response) : formatted(call.response)}</pre></> : <p>未采集</p>}</div></div>}
        {tab === '日志' && <div role="tabpanel"><div className="mapping-toolbar"><label>级别<select aria-label="日志级别" value={logLevel} onChange={event => setLogLevel(event.target.value)}><option value="">全部</option><option value="error">错误</option><option value="info">信息</option></select></label><label>范围<input aria-label="日志范围" value={logScope} onChange={event => setLogScope(event.target.value)} /></label><label>来源<select aria-label="日志来源" value={logSource} onChange={event => setLogSource(event.target.value)}><option value="">全部</option><option value="model_call">模型调用</option><option value="run_event">执行事件</option></select></label><label>关键字<input aria-label="日志关键字" value={logQuery} onChange={event => setLogQuery(event.target.value)} /></label></div><div className="diagnostic-list">{logs.map(item => <button key={item.id} onClick={() => { if (item.source === 'model_call') { setSelectedCall(item.id.slice(5)); setTab('输入与输出') } else { setSelectedNode(Number(item.id.slice(6))); setTab('执行时间线') } }}><span>{item.level} · {item.source} · {item.event_type || item.error_code || ''}</span><small>{time(item.created_at)} · {item.scope_id || detail.run.id} · {item.duration_ms ?? '—'} ms</small></button>)}{!logs.length && <p>没有匹配的日志。</p>}</div></div>}
        {tab === '产物' && <div role="tabpanel"><div className="diagnostic-list">{detail.artifacts.map(item => <article key={item.id} className="result-card"><h3>{item.kind} · v{item.version}</h3><p>{item.status} · {time(item.created_at)}</p><p className="mono">{item.id}</p><p>来源：{item.source_artifact_ids.length ? item.source_artifact_ids.join('、') : '无'}</p></article>)}{!detail.artifacts.length && <p>当前 Run 无产物。</p>}</div><button className="button-secondary" onClick={() => void download()}>下载脱敏诊断包</button></div>}
      </>}
    </>}
  </section>
}
