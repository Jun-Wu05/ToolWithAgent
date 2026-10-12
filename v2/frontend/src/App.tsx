import { useCallback, useEffect, useRef, useState } from 'react'
import { api, saveDownload, type ClassificationArtifact, type Conversation, type ConversationSummary, type FieldMappingArtifact, type FileRecord, type Identity, type MappingInput } from './api'
import { MappingWorkspace } from './MappingWorkspace'

const statusName: Record<string, string> = {
  queued: '排队中', pending: '排队中', running: '运行中', succeeded: '已完成',
  completed: '已完成', failed: '失败', cancelled: '已取消'
}
const runningStatus = new Set(['queued', 'pending', 'running'])
const readTheme = () => localStorage.getItem('twa-v2-theme') === 'dark' ? 'dark' : 'light'
const readableTime = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''

type MappingSource = { id: string; kind: 'file' | 'classification'; label: string }
type SourceFields = Pick<MappingInput, 'product' | 'log_vendor' | 'data_source'>
function MappingForm({ source, submitting, onSubmit, onCancel }: { source: MappingSource; submitting: boolean; onSubmit: (fields: SourceFields) => Promise<void>; onCancel: () => void }) {
  const [product, setProduct] = useState('')
  const [vendor, setVendor] = useState('')
  const [dataSource, setDataSource] = useState('')
  const [error, setError] = useState('')
  const live = useRef(true)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  return <form className="mapping-form" aria-label="标准字段映射参数" onSubmit={event => {
    event.preventDefault()
    if (!product.trim() || !vendor.trim() || submitting) return
    setError('')
    void onSubmit({ product: product.trim(), log_vendor: vendor.trim(), ...(dataSource.trim() ? { data_source: dataSource.trim() } : {}) }).catch(caught => {
      if (live.current) setError(caught instanceof Error ? caught.message : '字段映射未能启动，请重试。')
    })
  }}><p>标准字段映射：{source.label}</p><div className="mapping-form-fields"><label>产品<input required maxLength={160} value={product} onChange={event => setProduct(event.target.value)} disabled={submitting} /></label><label>厂商<input required maxLength={160} value={vendor} onChange={event => setVendor(event.target.value)} disabled={submitting} /></label><label>数据源（可选）<input maxLength={160} placeholder="留空自动补全" value={dataSource} onChange={event => setDataSource(event.target.value)} disabled={submitting} /></label></div>{error && <p role="alert" className="mapping-error">{error}</p>}<div className="mapping-actions"><button className="button-primary" type="submit" disabled={submitting || !product.trim() || !vendor.trim()}>{submitting ? '启动中…' : '开始映射'}</button><button className="button-secondary" type="button" onClick={onCancel} disabled={submitting}>取消</button></div></form>
}

export function App() {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [identities, setIdentities] = useState<Identity[]>([])
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [draft, setDraft] = useState('')
  const [theme, setTheme] = useState<'light' | 'dark'>(readTheme)
  const [drawerId, setDrawerId] = useState<string | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [mappingSource, setMappingSource] = useState<MappingSource | null>(null)
  const [mappingId, setMappingId] = useState<string | null>(null)
  const [downloadId, setDownloadId] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<{ id: string; message: string } | null>(null)
  const mappingReceipt = useRef<{ payload: string; key: string } | null>(null)
  const returnTarget = useRef<string | null>(null)
  const [featureFields, setFeatureFields] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const eventSequence = useRef(0)
  const activeViewId = useRef<string | null>(null)
  const viewToken = useRef(0)
  const refreshToken = useRef(0)

  useEffect(() => {
    if (mappingId || !returnTarget.current) return
    const card = document.getElementById('mapping-' + returnTarget.current)
    card?.scrollIntoView?.({ block: 'center' })
    card?.querySelector<HTMLButtonElement>('button')?.focus()
    returnTarget.current = null
  }, [mappingId])
  const resetMapping = () => { setMappingId(null); setMappingSource(null); setDownloadId(null); setDownloadError(null); mappingReceipt.current = null; returnTarget.current = null }
  const refreshList = useCallback(async () => {
    const result = await api.conversations()
    setConversations(result.items)
    return result.items
  }, [])
  const refreshActive = useCallback(async (id: string) => {
    if (id !== activeViewId.current) return
    const version = viewToken.current
    const request = ++refreshToken.current
    const detail = await api.conversation(id)
    if (version !== viewToken.current || request !== refreshToken.current || id !== activeViewId.current) return
    setConversation(detail)
    const latest = await api.conversations()
    if (version === viewToken.current && request === refreshToken.current) setConversations(latest.items)
  }, [])
  const initialize = useCallback(async () => {
    const version = ++viewToken.current
    setLoading(true)
    setError('')
    try {
      const [me, list] = await Promise.all([api.me(), api.conversations()])
      if (version !== viewToken.current) return
      setIdentity(me)
      setConversations(list.items)
      api.identities().then(result => { if (version === viewToken.current) setIdentities(result.items) }).catch(() => { if (version === viewToken.current) setIdentities([]) })
      const saved = sessionStorage.getItem('twa-v2-active')
      const chosen = list.items.find(item => item.id === saved)?.id || list.items[0]?.id || null
      activeViewId.current = chosen
      setActiveId(chosen)
      if (chosen) {
        const detail = await api.conversation(chosen)
        if (version === viewToken.current) setConversation(detail)
      }
      else setConversation(null)
    } catch (caught) {
      if (version === viewToken.current) setError(caught instanceof Error ? caught.message : '工作台加载失败，请重试。')
    } finally { if (version === viewToken.current) setLoading(false) }
  }, [])
  useEffect(() => { void initialize() }, [initialize])
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('twa-v2-theme', theme)
  }, [theme])
  useEffect(() => {
    if (!activeId) return
    sessionStorage.setItem('twa-v2-active', activeId)
    eventSequence.current = 0
    let live = true
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    const connect = () => {
      source = new EventSource(api.eventsUrl(activeId, eventSequence.current), { withCredentials: true })
      source.onmessage = event => {
        try {
          const record = JSON.parse(event.data) as { sequence?: number }
          eventSequence.current = Math.max(eventSequence.current, record.sequence || Number(event.lastEventId) || 0)
        } catch { /* A refresh still reconciles the server state. */ }
        if (live) void refreshActive(activeId).catch(() => setNotice('实时更新暂不可用，可刷新恢复。'))
      }
      source.onerror = () => {
        source?.close()
        if (live) {
          setNotice('实时连接中断，正在重连。')
          timer = setTimeout(() => { if (live) { void refreshActive(activeId).catch(() => {}); connect() } }, 2500)
        }
      }
    }
    connect()
    return () => { live = false; source?.close(); if (timer) clearTimeout(timer) }
  }, [activeId, refreshActive])
  const selectConversation = async (id: string) => {
    const version = ++viewToken.current
    activeViewId.current = id
    setActiveId(id)
    setConversation(null)
    setLoading(true)
    resetMapping(); setActionBusy(null); setNotice('')
    setDrawerId(null)
    setNavOpen(false)
    setError('')
    try {
      const detail = await api.conversation(id)
      if (version === viewToken.current) setConversation(detail)
    } catch (caught) {
      if (version === viewToken.current) setError(caught instanceof Error ? caught.message : '会话加载失败。')
    } finally { if (version === viewToken.current) setLoading(false) }
  }
  const createConversation = async () => {
    setBusy(true); setError('')
    try {
      const item = await api.createConversation()
      await refreshList()
      await selectConversation(item.id)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '创建会话失败。') }
    finally { setBusy(false) }
  }
  const ensureConversation = async () => {
    if (activeId) return activeId
    const item = await api.createConversation()
    ++viewToken.current
    activeViewId.current = item.id
    setActiveId(item.id)
    setConversation({ ...item, messages: [], files: [], runs: [] })
    await refreshList()
    return item.id
  }
  const send = async () => {
    const content = draft.trim()
    if (!content || busy) return
    setBusy(true); setError('')
    try {
      const id = await ensureConversation()
      await api.sendMessage(id, content)
      setDraft('')
      await refreshActive(id)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '消息发送失败。') }
    finally { setBusy(false) }
  }
  const upload = async (file: File) => {
    setBusy(true); setError('')
    try {
      const id = await ensureConversation()
      await api.uploadFile(id, file)
      setNotice('文件已上传，正在校验。')
      await refreshActive(id)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '上传失败，请检查文件后重试。') }
    finally { setBusy(false); if (fileInput.current) fileInput.current.value = '' }
  }
  const parseLog = async (file: FileRecord) => {
    if (!activeId || actionBusy) return
    setActionBusy(file.id); setError('')
    try {
      await api.logParse(activeId, file.id, featureFields[file.id]?.trim() || undefined)
      setNotice('日志类型提取已排队。')
      await refreshActive(activeId)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '日志类型提取未能启动。') }
    finally { setActionBusy(null) }
  }
  const submitKnowledge = async (artifact: ClassificationArtifact) => {
    if (!activeId || actionBusy) return
    setActionBusy(artifact.id); setError('')
    try {
      await api.submitLogKnowledge(artifact.id)
      setNotice('日志知识申请已排队。')
      await refreshActive(activeId)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '日志知识申请未能启动。') }
    finally { setActionBusy(null) }
  }
  const startMapping = async (fields: SourceFields) => {
    if (!activeId || !mappingSource || actionBusy || identity?.role !== 'user') return
    const version = viewToken.current
    const id = activeId
    const input: MappingInput = { ...fields, ...(mappingSource.kind === 'file' ? { file_id: mappingSource.id } : { classification_artifact_id: mappingSource.id }) }
    const payload = JSON.stringify([id, input])
    if (mappingReceipt.current?.payload !== payload) mappingReceipt.current = { payload, key: crypto.randomUUID() }
    setActionBusy(mappingSource.id)
    try {
      await api.fieldMapping(id, input, mappingReceipt.current.key)
      if (version !== viewToken.current) return
      setMappingSource(null); mappingReceipt.current = null
      setNotice('标准字段映射已排队。')
      await refreshActive(id)
    } finally { if (version === viewToken.current) setActionBusy(null) }
  }
  const downloadMapping = async (id: string) => {
    if (downloadId) return
    const version = viewToken.current
    setDownloadId(id); setDownloadError(null)
    try {
      const file = await api.mappingDownload(id)
      if (version === viewToken.current) saveDownload(file)
    } catch (caught) {
      if (version === viewToken.current) setDownloadError({ id, message: caught instanceof Error ? caught.message : '配置下载失败，请重试。' })
    } finally { if (version === viewToken.current) setDownloadId(null) }
  }
  const mappingForm = (source: MappingSource) => mappingSource?.id === source.id && mappingSource.kind === source.kind && <MappingForm key={source.id} source={source} submitting={!!actionBusy} onSubmit={startMapping} onCancel={() => setMappingSource(null)} />
  const retryRun = async (runId: string) => {
    if (!activeId || actionBusy) return
    setActionBusy(runId); setError('')
    try { await api.retryRun(runId); await refreshActive(activeId) }
    catch (caught) { setError(caught instanceof Error ? caught.message : '重新执行失败。') }
    finally { setActionBusy(null) }
  }
  const stopRun = async (runId: string) => {
    if (!activeId || actionBusy || !window.confirm('确认停止这次执行？已完成的正式结果会保留。')) return
    setActionBusy(runId); setError('')
    try {
      const { token } = await api.cancelToken(runId)
      await api.cancelRun(runId, token)
      await refreshActive(activeId)
    } catch (caught) { setError(caught instanceof Error ? caught.message : '停止执行失败。') }
    finally { setActionBusy(null) }
  }
  const switchIdentity = async (userId: string) => {
    ++viewToken.current
    activeViewId.current = null
    setActiveId(null); resetMapping(); setConversation(null); setDrawerId(null); setNotice(''); setActionBusy(null); setLoading(true)
    setBusy(true); setError('')
    try {
      await api.selectIdentity(userId)
      sessionStorage.removeItem('twa-v2-active')
      setActiveId(null); setConversation(null); setDrawerId(null)
      await initialize()
    } catch (caught) { setError(caught instanceof Error ? caught.message : '切换身份失败。') }
    finally { setBusy(false) }
  }
  const activeRun = conversation?.runs.find(run => runningStatus.has(run.status))
  const drawer = conversation?.runs.find(run => run.id === drawerId) || null
  const mappingArtifact = conversation?.artifacts?.find((artifact): artifact is FieldMappingArtifact => artifact.kind === 'field_mapping' && artifact.id === mappingId)
  const classificationArtifacts = conversation?.artifacts?.filter((artifact): artifact is ClassificationArtifact => artifact.kind === 'log_classification' && artifact.status === 'published') || []
  const mappingArtifacts = conversation?.artifacts?.filter((artifact): artifact is FieldMappingArtifact => artifact.kind === 'field_mapping') || []
  return <div className="app">
    <button className="mobile-nav-toggle" onClick={() => setNavOpen(!navOpen)} aria-label="切换导航">导航</button>
    <aside className={'sidebar ' + (navOpen ? 'sidebar-open' : '')}>
      <div className="brand"><span className="brand-mark">T</span><span>ToolWithAgent <small>V2 工作台</small></span></div>
      <button className="new-conversation" onClick={() => void createConversation()} disabled={busy}>＋ 新会话</button>
      <nav aria-label="主导航"><div className="nav-item selected">工作台</div><div className="nav-item muted" title="后续版本提供">任务</div><div className="nav-item muted" title="后续版本提供">运行记录</div></nav>
      <div className="recent-title">最近会话</div>
      <div className="recent-list">{conversations.length ? conversations.map(item => <button key={item.id} className={'recent-item ' + (item.id === activeId ? 'active' : '')} onClick={() => void selectConversation(item.id)}><span className="recent-name">{item.title || '未命名会话'}</span><span className="recent-time">{readableTime(item.updated_at)}</span></button>) : <p className="sidebar-empty">新建会话开始工作</p>}</div>
      <div className="identity">
        <span className="avatar">{identity?.display_name?.slice(0, 1) || '用'}</span>
        <span className="identity-name">{identity?.display_name || '加载中'}<small>{identity?.role || 'user'}</small></span>
        {identities.length > 0 && <select aria-label="开发身份切换" value={identity?.id || ''} onChange={event => void switchIdentity(event.target.value)} disabled={busy}>{identities.map(item => <option key={item.id} value={item.id}>{item.display_name} ({item.role})</option>)}</select>}
      </div>
    </aside>
    <main className="workspace">
      <header className="workspace-header"><div><h1>{conversation?.title || '工作台'}</h1><p>{conversation ? '会话与执行状态' : '从一条消息或一个文件开始'}</p></div><div className="header-actions"><button className="icon-button" aria-label={theme === 'light' ? '切换深色主题' : '切换浅色主题'} title={theme === 'light' ? '切换深色主题' : '切换浅色主题'} onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>{theme === 'light' ? '深色主题' : '浅色主题'}</button></div></header>
      {error && <div role="alert" className="feedback error"><span>{error}</span><button onClick={() => { setError(''); void initialize() }}>重试</button></div>}
      {notice && <div role="status" className="feedback notice"><span>{notice}</span><button aria-label="关闭提示" onClick={() => setNotice('')}>关闭</button></div>}
      <div className="conversation-content">
        {mappingArtifact && !loading ? <MappingWorkspace key={identity?.id + ':' + activeId + ':' + mappingArtifact.id} artifact={mappingArtifact} onBack={() => { returnTarget.current = mappingArtifact.id; setMappingId(null) }} onDownload={() => void downloadMapping(mappingArtifact.id)} downloading={downloadId === mappingArtifact.id} downloadError={downloadError?.id === mappingArtifact.id ? downloadError.message : ''} /> : loading ? <div className="empty-state"><h2>正在加载工作台…</h2></div> : !conversation ? <div className="empty-state"><h2>开始一项日志规则任务</h2><p>上传日志或规则文件，或者先描述要处理的内容。</p><button className="button-primary" onClick={() => fileInput.current?.click()}>上传文件</button></div> : <>
          {conversation.messages.length === 0 && conversation.files.length === 0 && <div className="empty-state compact"><h2>这段会话还没有内容</h2><p>发送消息或上传文件，工作台会在这里显示进展。</p></div>}
          <div className="timeline">{conversation.messages.map(message => <article className={'message ' + (message.actor === 'user' ? 'from-user' : '')} key={message.id}><div className="message-head"><strong>{message.actor === 'user' ? '你' : 'ToolWithAgent'}</strong><time>{readableTime(message.created_at)}</time></div><p>{message.content}</p></article>)}
            {conversation.files.length > 0 && <section className="activity-section"><h2>输入文件</h2>{conversation.files.map(file => <div className="file-row" key={file.id}><span className="file-icon">▤</span><div className="file-main"><strong>{file.name}</strong><small>{file.size != null ? (file.size / 1024).toFixed(1) + ' KB' : '已上传'}</small>{identity?.role === 'user' && file.parse_status === 'succeeded' && /\.(txt|log|json|jsonl|csv|xlsx)$/i.test(file.name) && <div className="file-actions"><label>分类特征字段（可选）<input aria-label={file.name + ' 分类特征字段'} placeholder="自动识别" value={featureFields[file.id] || ''} onChange={event => setFeatureFields({ ...featureFields, [file.id]: event.target.value })} disabled={!!actionBusy} /></label><button className="button-secondary" onClick={() => void parseLog(file)} disabled={!!actionBusy}>{actionBusy === file.id ? '启动中…' : '提取日志类型'}</button></div>}{identity?.role === 'user' && file.mapping_eligible && <><button className="button-secondary mapping-entry" onClick={() => setMappingSource({ id: file.id, kind: 'file', label: file.name })} disabled={!!actionBusy}>标准字段映射</button>{mappingForm({ id: file.id, kind: 'file', label: file.name })}</>}</div><span className="file-status">{statusName[file.parse_status || ''] || '已登记'}</span></div>)}</section>}
            {classificationArtifacts.length > 0 && <section className="activity-section"><h2>日志解析结果</h2>{classificationArtifacts.map(artifact => <article className="result-card" key={artifact.id}><div className="result-heading"><strong>日志类型提取完成</strong><span>{readableTime(artifact.created_at)}</span></div><p>覆盖率：{artifact.summary.coverage.matched_lines} / {artifact.summary.coverage.total_lines}</p><div className="result-types">{artifact.summary.log_types.map((item, index) => <span key={item.name + index}>{item.name} · {item.count}</span>)}</div><p className="rule-summary">解析规则：{artifact.summary.rule_summary}</p>{artifact.submission_status && <p role="status">申请状态：{{ created: '待审核', pending_duplicate: '已有待审核申请', already_approved: '已批准', stale: '结果已过期', error: '提交失败' }[artifact.submission_status] || statusName[artifact.submission_status] || artifact.submission_status}{artifact.application_id ? '（申请编号 ' + artifact.application_id + '）' : ''}</p>}{identity?.role === 'user' && artifact.submission_eligible && (!artifact.submission_status || artifact.submission_status === 'error') && <button className="button-secondary" onClick={() => void submitKnowledge(artifact)} disabled={!!actionBusy}>{actionBusy === artifact.id ? '提交中…' : '申请加入知识库'}</button>}{identity?.role === 'user' && artifact.mapping_eligible && <><button className="button-secondary" onClick={() => setMappingSource({ id: artifact.id, kind: 'classification', label: '日志分类结果' })} disabled={!!actionBusy}>标准字段映射</button>{mappingForm({ id: artifact.id, kind: 'classification', label: '日志分类结果' })}</>}</article>)}</section>}
            {mappingArtifacts.length > 0 && <section className="activity-section"><h2>字段映射结果</h2>{mappingArtifacts.map(artifact => <article className="result-card" key={artifact.id} id={'mapping-' + artifact.id}><div className="result-heading"><strong>标准字段映射完成</strong><span>{readableTime(artifact.created_at)}</span></div><p>{artifact.summary.rule_count} 条子规则，{artifact.summary.field_count} 个字段</p><div className="mapping-counts"><span>映射成功 {artifact.summary.matched_count}</span><span>未匹配 {artifact.summary.unmatched_count}</span><span>解析异常 {artifact.summary.parse_error_count}</span></div>{(artifact.summary.uncertain_annotation_count || 0) > 0 && <p className="mapping-warning">待人工确认：{artifact.summary.uncertain_annotation_count} 条事件名称标注。</p>}{artifact.summary.warning_codes?.includes('threat_chain_warning') && <p className="mapping-warning">威胁类型处理有提醒，请查看结果。</p>}{!artifact.current && <p className="mapping-warning">结果已过期，可查看和下载历史配置。</p>}<div className="mapping-actions"><button className="button-secondary" onClick={() => setMappingId(artifact.id)}>查看结果</button><button className="button-secondary" onClick={() => void downloadMapping(artifact.id)} disabled={!!downloadId}>{downloadId === artifact.id ? '下载中…' : '下载配置'}</button></div>{downloadError?.id === artifact.id && <p className="mapping-error" role="alert">{downloadError.message}</p>}</article>)}</section>}
            {conversation.runs.length > 0 && <section className="activity-section"><h2>执行记录</h2>{conversation.runs.map(run => <button className="run-row" key={run.id} onClick={() => setDrawerId(run.id)}><span className={'status-dot status-' + run.status}></span><span className="run-label">{run.kind || run.type || '文件校验'}</span><span className="run-status">{statusName[run.status] || run.status}</span><span className="run-detail">执行详情 ›</span></button>)}</section>}
          </div>
        </>}
      </div>
      <div className="composer-region">{activeRun && <div className="active-run"><span className="pulse"></span><span>{activeRun.kind === 'field_mapping' ? '标准字段映射' : activeRun.kind === 'log_parse' ? '日志类型提取' : activeRun.kind === 'log_knowledge_submit' ? '日志知识申请' : '文件校验'}{statusName[activeRun.status] === '排队中' ? '排队中' : '进行中'}</span><button onClick={() => setDrawerId(activeRun.id)}>查看执行详情</button>{identity?.role === 'user' && <button onClick={() => void stopRun(activeRun.id)} disabled={!!actionBusy}>停止</button>}</div>}
        <div className="composer"><textarea aria-label="消息内容" placeholder="描述要处理的日志、字段或规则…" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} rows={2} disabled={busy || loading} /><div className="composer-toolbar"><div><input ref={fileInput} type="file" hidden aria-label="选择文件" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file) }} /><button className="attach-button" onClick={() => fileInput.current?.click()} disabled={busy || loading}>＋ 添加文件</button><span className="composer-hint">Enter 发送 · Shift+Enter 换行</span></div><button className="button-primary send-button" onClick={() => void send()} disabled={!draft.trim() || busy || loading}>{busy ? '处理中…' : '发送'}</button></div></div>
      </div>
    </main>
    {drawer && <><div className="drawer-backdrop" onClick={() => setDrawerId(null)}></div><aside className="drawer" aria-label="执行详情"><header><div><small>执行详情</small><h2>{drawer.kind === 'field_mapping' ? '标准字段映射' : drawer.kind === 'log_parse' ? '日志类型提取' : drawer.kind === 'log_knowledge_submit' ? '日志知识申请' : '文件校验'}</h2></div><button className="icon-button" aria-label="关闭执行详情" onClick={() => setDrawerId(null)}>关闭</button></header><dl><dt>状态</dt><dd>{statusName[drawer.status] || drawer.status}</dd><dt>Run ID</dt><dd className="mono">{drawer.id}</dd>{drawer.task_id && <><dt>Task ID</dt><dd className="mono">{drawer.task_id}</dd></>}{drawer.error_code && <><dt>错误代码</dt><dd className="mono">{drawer.error_code}</dd></>}{drawer.error_message && <><dt>原因</dt><dd>{drawer.error_message}</dd></>}</dl>{identity?.role === 'user' && (drawer.status === 'failed' || drawer.status === 'cancelled') && <button className="button-secondary" onClick={() => void retryRun(drawer.id)} disabled={!!actionBusy}>重新执行</button>}<button className="button-secondary" onClick={async () => { try { if (activeId) await refreshActive(activeId) } catch { setNotice('执行详情刷新失败。') } }}>刷新状态</button></aside></>}
  </div>
}
