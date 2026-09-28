import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Conversation, type ConversationSummary, type Identity } from './api'

const statusName: Record<string, string> = {
  queued: '排队中', pending: '排队中', running: '正在校验', succeeded: '已完成',
  completed: '已完成', failed: '失败', cancelled: '已取消'
}
const runningStatus = new Set(['queued', 'pending', 'running'])
const readTheme = () => localStorage.getItem('twa-v2-theme') === 'dark' ? 'dark' : 'light'
const readableTime = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''

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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const eventSequence = useRef(0)
  const viewToken = useRef(0)
  const refreshToken = useRef(0)

  const refreshList = useCallback(async () => {
    const result = await api.conversations()
    setConversations(result.items)
    return result.items
  }, [])
  const refreshActive = useCallback(async (id: string) => {
    const version = viewToken.current
    const request = ++refreshToken.current
    const detail = await api.conversation(id)
    if (version !== viewToken.current || request !== refreshToken.current) return
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
      api.identities().then(result => setIdentities(result.items)).catch(() => setIdentities([]))
      const saved = sessionStorage.getItem('twa-v2-active')
      const chosen = list.items.find(item => item.id === saved)?.id || list.items[0]?.id || null
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
    setActiveId(id)
    setDrawerId(null)
    setNavOpen(false)
    setError('')
    try {
      const detail = await api.conversation(id)
      if (version === viewToken.current) setConversation(detail)
    } catch (caught) {
      if (version === viewToken.current) setError(caught instanceof Error ? caught.message : '会话加载失败。')
    }
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
  const switchIdentity = async (userId: string) => {
    ++viewToken.current
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
        {loading ? <div className="empty-state"><h2>正在加载工作台…</h2></div> : !conversation ? <div className="empty-state"><h2>开始一项日志规则任务</h2><p>上传日志或规则文件，或者先描述要处理的内容。</p><button className="button-primary" onClick={() => fileInput.current?.click()}>上传文件</button></div> : <>
          {conversation.messages.length === 0 && conversation.files.length === 0 && <div className="empty-state compact"><h2>这段会话还没有内容</h2><p>发送消息或上传文件，工作台会在这里显示进展。</p></div>}
          <div className="timeline">{conversation.messages.map(message => <article className={'message ' + (message.actor === 'user' ? 'from-user' : '')} key={message.id}><div className="message-head"><strong>{message.actor === 'user' ? '你' : 'ToolWithAgent'}</strong><time>{readableTime(message.created_at)}</time></div><p>{message.content}</p></article>)}
            {conversation.files.length > 0 && <section className="activity-section"><h2>输入文件</h2>{conversation.files.map(file => <div className="file-row" key={file.id}><span className="file-icon">▤</span><div><strong>{file.name}</strong><small>{file.size != null ? (file.size / 1024).toFixed(1) + ' KB' : '已上传'}</small></div><span className="file-status">{statusName[file.parse_status || ''] || '已登记'}</span></div>)}</section>}
            {conversation.runs.length > 0 && <section className="activity-section"><h2>执行记录</h2>{conversation.runs.map(run => <button className="run-row" key={run.id} onClick={() => setDrawerId(run.id)}><span className={'status-dot status-' + run.status}></span><span className="run-label">{run.kind || run.type || '文件校验'}</span><span className="run-status">{statusName[run.status] || run.status}</span><span className="run-detail">执行详情 ›</span></button>)}</section>}
          </div>
        </>}
      </div>
      <div className="composer-region">{activeRun && <div className="active-run"><span className="pulse"></span><span>文件校验{statusName[activeRun.status] === '排队中' ? '排队中' : '进行中'}</span><button onClick={() => setDrawerId(activeRun.id)}>查看执行详情</button></div>}
        <div className="composer"><textarea aria-label="消息内容" placeholder="描述要处理的日志、字段或规则…" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() } }} rows={2} disabled={busy || loading} /><div className="composer-toolbar"><div><input ref={fileInput} type="file" hidden aria-label="选择文件" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file) }} /><button className="attach-button" onClick={() => fileInput.current?.click()} disabled={busy || loading}>＋ 添加文件</button><span className="composer-hint">Enter 发送 · Shift+Enter 换行</span></div><button className="button-primary send-button" onClick={() => void send()} disabled={!draft.trim() || busy || loading}>{busy ? '处理中…' : '发送'}</button></div></div>
      </div>
    </main>
    {drawer && <><div className="drawer-backdrop" onClick={() => setDrawerId(null)}></div><aside className="drawer" aria-label="执行详情"><header><div><small>执行详情</small><h2>文件校验</h2></div><button className="icon-button" aria-label="关闭执行详情" onClick={() => setDrawerId(null)}>关闭</button></header><dl><dt>状态</dt><dd>{statusName[drawer.status] || drawer.status}</dd><dt>Run ID</dt><dd className="mono">{drawer.id}</dd>{drawer.task_id && <><dt>Task ID</dt><dd className="mono">{drawer.task_id}</dd></>}{drawer.error_code && <><dt>错误代码</dt><dd className="mono">{drawer.error_code}</dd></>}{drawer.error_message && <><dt>原因</dt><dd>{drawer.error_message}</dd></>}</dl><button className="button-secondary" onClick={async () => { try { if (activeId) await refreshActive(activeId) } catch { setNotice('执行详情刷新失败。') } }}>刷新状态</button></aside></>}
  </div>
}
