import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, saveDownload, type ClassificationArtifact, type Conversation, type ConversationSummary, type FieldMappingArtifact, type FileRecord, type Identity, type MappingInput, type MappingDraft, type MappingDraftSummary, type ApiError, type Artifact, type Message, type Run, type ProgressSummary, type Suggestion } from './api'
import { type WorkspaceTab } from './WorkspaceViews'
import { TrajectoryLedger } from './TrajectoryLedger'
import { ConversationTimeline, type TimelineActions } from './ConversationTimeline'
import { StatusText, TaskHintBar } from './VisualPrimitives'
import { FieldChangesWorkspace } from './FieldChangesWorkspace'
import { MappingWorkspace } from './MappingWorkspace'
import { MappingSummaryCard } from './ConversationMappingSummary'
import { AdminConsole } from './AdminConsole'
import { DeveloperConsole } from './DeveloperConsole'
import { RunDiagnostics } from './RunDiagnostics'
import { UserHistory } from './UserHistory'
import { MappingDialog } from './MappingDialog'
import { BusinessOperations, BusinessConfirmation, businessName, ArtifactValues, progressLabel } from './BusinessWorkspace'
import { LogClassificationCard } from './LogClassificationResult'

const statusName: Record<string, string> = {
  queued: '排队中', pending: '排队中', running: '运行中', succeeded: '已完成',
  waiting_confirmation: '待确认', completed: '已完成', failed: '失败', cancelled: '已取消'
}
// #435 空状态场景模板库：点击只填入话术（可改可拼），不直接触发命令。
const SCENE_TEMPLATES: { title: string; hint: string; prompt: string }[] = [
  { title: '提取字段枚举值', hint: '上传日志后一句话提取某字段的全部取值，单步出结果', prompt: '提取【字段名】的枚举值' },
  { title: '日志类型提取 + 字段映射', hint: '识别日志结构，把原始字段映射到标准字段目录', prompt: '对上传的日志做日志类型提取，然后进行标准字段映射' },
  { title: '修改映射', hint: '新增、删除、合并映射字段，一句话可带多个操作', prompt: '给当前映射增加【字段a】，删除【字段b】' },
  { title: '威胁类型标注', hint: '为事件字段标注威胁类型，支持链路填充', prompt: '对事件名称字段做威胁类型标注' },
  { title: '导出规则配置', hint: '把当前映射导出为可下载的配置文件', prompt: '导出当前的规则配置' },
  { title: '你能做什么？', hint: '不清楚从哪开始时，直接问我', prompt: '你能做什么？' },
]
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
  const [developerDiagnostics, setDeveloperDiagnostics] = useState(false)
  const [visitedTabs, setVisitedTabs] = useState<WorkspaceTab[]>(['conversation'])
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('conversation')
  const [traceTarget, setTraceTarget] = useState<{ id: string; token: number } | null>(null)
  const [diagnosticRunId, setDiagnosticRunId] = useState<string | null>(null)
  const [resourceTabs, setResourceTabs] = useState<('mapping' | 'results')[]>([])
  const [activeResource, setActiveResource] = useState<'mapping' | 'results'>('mapping')
  const [resourceOpen, setResourceOpen] = useState(false)
  const [resourceWidth, setResourceWidth] = useState<number | null>(null)
  const layoutRef = useRef<HTMLDivElement>(null)
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null)
  const resourceTrigger = useRef<HTMLElement | null>(null)
  const openResource = (tab: 'mapping' | 'results') => {
    if (editingPendingRef.current && activeResource === 'mapping' && tab !== 'mapping') { setNotice('请先重试保存或取消当前字段修改。'); return false }
    if (document.activeElement instanceof HTMLElement) resourceTrigger.current = document.activeElement
    setResourceTabs(current => current.includes(tab) ? current : [...current, tab])
    setActiveResource(tab)
    setResourceOpen(true)
    if (workspaceTab !== 'conversation') changeWorkspaceTab('conversation')
    return true
  }
  const collapseResource = () => { setResourceOpen(false); if (resourceTrigger.current?.isConnected) resourceTrigger.current.focus() }
  const closeResource = (tab: 'mapping' | 'results') => {
    if (tab === 'mapping' && editingPendingRef.current) { setNotice('请先重试保存或取消当前字段修改。'); return }
    const remaining = resourceTabs.filter(item => item !== tab)
    setResourceTabs(remaining)
    if (!remaining.length) collapseResource()
    else if (activeResource === tab) setActiveResource(remaining.at(-1)!)
  }
  const selectResourceTab = (tab: 'mapping' | 'results') => {
    if (editingPendingRef.current && activeResource === 'mapping' && tab !== 'mapping') { setNotice('请先重试保存或取消当前字段修改。'); return false }
    setActiveResource(tab)
    return true
  }
  const resourceTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, tab: 'mapping' | 'results') => {
    const index = resourceTabs.indexOf(tab)
    const next = event.key === 'ArrowRight' ? resourceTabs[(index + 1) % resourceTabs.length] : event.key === 'ArrowLeft' ? resourceTabs[(index - 1 + resourceTabs.length) % resourceTabs.length] : event.key === 'Home' ? resourceTabs[0] : event.key === 'End' ? resourceTabs.at(-1) : undefined
    if (!next) return
    event.preventDefault()
    if (selectResourceTab(next)) event.currentTarget.closest('[role="tablist"]')?.querySelector<HTMLButtonElement>(`[data-resource-tab="${next}"]`)?.focus()
  }
  const viewScroll = useRef<Record<string, number>>({})
  const currentTab = useRef<WorkspaceTab>('conversation')
  const contentRef = useRef<HTMLDivElement>(null)
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [identities, setIdentities] = useState<Identity[]>([])
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [draft, setDraft] = useState('')
  const [theme, setTheme] = useState<'light' | 'dark'>(readTheme)
  const [latestProgress, setLatestProgress] = useState<{runId: string; summary: ProgressSummary} | null>(null)
  const artifactRequest = useRef(0)
  const [artifactContent, setArtifactContent] = useState<Record<string, unknown> | null>(null)
  const [artifactError, setArtifactError] = useState('')
  const [artifactLoading, setArtifactLoading] = useState(false)
  const clearReceipt = useRef<{id: string; key: string} | null>(null)
  const [clearBusy, setClearBusy] = useState(false)
  const [clearError, setClearError] = useState('')
  const [uploadRole, setUploadRole] = useState<'primary' | 'enum_mapping'>('primary')
  const [pendingConfirmation, setPendingConfirmation] = useState<{id: string; content: string; version: number; run: Run} | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [mappingSource, setMappingSource] = useState<MappingSource | null>(null)
  const [fieldChangesId, setFieldChangesSelection] = useState<string | null>(null)
  const [mappingId, setMappingSelection] = useState<string | null>(null)
  const [mappingDraftId, setMappingDraftId] = useState<string | undefined>()
  const [editingPending, setEditingPending] = useState(false)
  const editingPendingRef = useRef(false)
  const [pendingSend, setPendingSend] = useState<{ id: string; content: string; version: number; drafts: MappingDraftSummary[] } | null>(null)
  const [resolutionError, setResolutionError] = useState('')
  const [resolutionConflict, setResolutionConflict] = useState(false)
  const applyReceipts = useRef(new Map<string, { revision: number; key: string }>())
  const [downloadId, setDownloadId] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<{ id: string; message: string } | null>(null)
  const mappingReceipt = useRef<{ payload: string; key: string } | null>(null)
  const [featureFields, setFeatureFields] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const eventSequence = useRef(0)
  const activeViewId = useRef<string | null>(null)
  const viewToken = useRef(0)
  const refreshToken = useRef(0)
  const stickToBottom = useRef(true)
  const lastMessageIdRef = useRef<string | null>(null)
  const [newReplies, setNewReplies] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [dismissedParamRuns, setDismissedParamRuns] = useState<string[]>([])
  const scrollConversationToEnd = (behavior: ScrollBehavior = 'auto') => {
    const pane = contentRef.current
    if (!pane) return
    if (typeof pane.scrollTo !== 'function') { pane.scrollTop = pane.scrollHeight; return }
    pane.scrollTo({ top: pane.scrollHeight, behavior })
  }
  const onConversationScroll = () => {
    const pane = contentRef.current
    if (pane) stickToBottom.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 140
  }
  useEffect(() => {
    if (workspaceTab !== 'conversation' || !conversation) return
    const lastId = conversation.messages.at(-1)?.id || null
    if (lastId === lastMessageIdRef.current) return
    const hadPrevious = lastMessageIdRef.current !== null
    lastMessageIdRef.current = lastId
    if (!hadPrevious) return
    if (stickToBottom.current) requestAnimationFrame(() => scrollConversationToEnd())
    else setNewReplies(true)
  }, [conversation, workspaceTab])

  const submitRename = async () => {
    const title = titleDraft.trim()
    if (!activeId || !title) return
    try {
      const renamed = await api.renameConversation(activeId, title)
      setRenaming(false)
      setConversation(current => current && current.id === activeId ? { ...current, title: renamed.title } : current)
      setConversations(list => list.map(item => item.id === activeId ? { ...item, title: renamed.title } : item))
    } catch (caught) { setError(caught instanceof Error ? caught.message : '重命名失败。') }
  }
  const submitInlineMapping = async (source: MappingSource, fields: SourceFields) => {
    if (!activeId || identity?.role !== 'user') return
    const input: MappingInput = { ...fields, file_id: source.id }
    await api.fieldMapping(activeId, input, crypto.randomUUID())
    setNotice('标准字段映射已排队。')
    await refreshActive(activeId)
  }
  const changeWorkspaceTab = useCallback((next: WorkspaceTab) => {
    if (contentRef.current) viewScroll.current[currentTab.current] = contentRef.current.scrollTop
    setVisitedTabs(current => current.includes(next) ? current : [...current, next]); setWorkspaceTab(next)
  }, [])
  const setMappingId = (id: string | null) => { if (editingPendingRef.current && id !== mappingId) { setNotice('请先重试保存或取消当前字段修改。'); return false } if (id && !openResource('mapping')) return false; setMappingSelection(id); if (id) setFieldChangesSelection(null); return true }
  const setFieldChangesId = (id: string | null) => { if (editingPendingRef.current && id) { setNotice('请先重试保存或取消当前字段修改。'); return } if (id && !openResource('results')) return; setFieldChangesSelection(id) }
  useLayoutEffect(() => { if (contentRef.current) contentRef.current.scrollTop = viewScroll.current[workspaceTab] || 0; currentTab.current = workspaceTab }, [workspaceTab])
  const resetMapping = () => { changeWorkspaceTab('conversation'); setVisitedTabs(['conversation']); setTraceTarget(null); setDiagnosticRunId(null); setResourceTabs([]); setResourceOpen(false); setResourceWidth(null); viewScroll.current = {}; setFieldChangesId(null); clearReceipt.current = null; setClearBusy(false); setClearError(''); setLatestProgress(null); ++artifactRequest.current; setSelectedResultId(null); setArtifactContent(null); setArtifactError(''); setArtifactLoading(false); setPendingConfirmation(null); setMappingDraftId(undefined); setEditingPending(false); editingPendingRef.current = false; setPendingSend(null); setResolutionError(''); setResolutionConflict(false); setMappingSelection(null); setMappingSource(null); setDownloadId(null); setDownloadError(null); mappingReceipt.current = null; }
  const refreshList = useCallback(async () => {
    const version = viewToken.current
    const result = await api.conversations()
    if (version === viewToken.current) setConversations(result.items)
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
    const version = viewToken.current
    let live = true
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | null = null
    const connect = () => {
      source = new EventSource(api.eventsUrl(activeId, eventSequence.current), { withCredentials: true })
      source.onmessage = event => {
        try {
          const record = JSON.parse(event.data) as { sequence?: number; event_type?: string; resource_id?: string; payload?: ProgressSummary }
          if (live && version === viewToken.current && record.event_type === 'run_progress' && record.resource_id && record.payload) {
            setLatestProgress({runId: record.resource_id, summary: record.payload})
          }
          eventSequence.current = Math.max(eventSequence.current, record.sequence || Number(event.lastEventId) || 0)
        } catch { /* A refresh still reconciles the server state. */ }
        if (live) void refreshActive(activeId).catch(() => { if (live && version === viewToken.current) setNotice('实时更新暂不可用，可刷新恢复。') })
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
    resetMapping(); setActionBusy(null); setBusy(false); setNotice('')
    setNavOpen(false)
    setError('')
    lastMessageIdRef.current = null
    stickToBottom.current = true
    setNewReplies(false)
    try {
      const detail = await api.conversation(id)
      if (version === viewToken.current) setConversation(detail)
    } catch (caught) {
      if (version === viewToken.current) setError(caught instanceof Error ? caught.message : '会话加载失败。')
    } finally { if (version === viewToken.current) setLoading(false) }
  }
  const createConversation = async () => {
    const version = viewToken.current
    setBusy(true); setError('')
    try {
      const item = await api.createConversation()
      if (!isCurrent(version)) return
      await refreshList()
      if (!isCurrent(version)) return
      await selectConversation(item.id)
    } catch (caught) { if (isCurrent(version)) setError(caught instanceof Error ? caught.message : '创建会话失败。') }
    finally { if (isCurrent(version)) setBusy(false) }
  }
  const isCurrent = (version: number, id?: string) => version === viewToken.current && (!id || id === activeViewId.current)
  const ensureConversation = async (version: number) => {
    if (!isCurrent(version)) return null
    if (activeViewId.current) return activeViewId.current
    const item = await api.createConversation()
    if (!isCurrent(version)) return null
    activeViewId.current = item.id
    setActiveId(item.id)
    setConversation({ ...item, messages: [], files: [], runs: [] })
    await refreshList()
    return isCurrent(version, item.id) ? item.id : null
  }
  const draftChanged = (next: MappingDraft) => {
    if (next.conversation_id !== activeViewId.current) return
    setConversation(current => current ? { ...current, drafts: [...(current.drafts || []).filter(item => item.id !== next.id), next] } : current)
  }
  const pendingChanged = (value: boolean) => { editingPendingRef.current = value; setEditingPending(value) }
  const unresolvedDrafts = (items: MappingDraftSummary[] = []) => items.filter(item => item.status === 'applying' || (item.status === 'active' && item.changed_count > 0))
  const applyAndWait = async (initial: MappingDraft, version: number): Promise<MappingDraft | null> => {
    const id = initial.conversation_id
    if (!isCurrent(version, id)) return null
    let current = initial
    if (current.status !== 'applying') {
      let receipt = applyReceipts.current.get(current.id)
      if (!receipt || receipt.revision !== current.revision) {
        receipt = { revision: current.revision, key: crypto.randomUUID() }
        applyReceipts.current.set(current.id, receipt)
      }
      const result = await api.applyMappingDraft(current.id, current.revision, receipt.key)
      if (!isCurrent(version, id)) return null
      current = result.draft
      draftChanged(current)
      await refreshActive(id)
    }
    if (!isCurrent(version, id)) return null
    while (current.status === 'applying') {
      if (!current.apply_run_id) throw new Error('应用执行信息不完整，请重新加载草稿。')
      const queriedRun = current.apply_run_id
      const [run, next] = await Promise.all([api.run(queriedRun), api.mappingDraft(current.id)])
      if (!isCurrent(version, id)) return null
      if (next.revision !== initial.revision) throw Object.assign(new Error('草稿已更新，已停止等待旧版本。请重新加载草稿。'), { code: 'draft_revision_conflict' })
      current = next
      draftChanged(current)
      // REST reads can straddle the atomic publication transaction. The applied
      // Draft is the publication receipt; an earlier queued Run read is harmless.
      if (current.apply_run_id && current.apply_run_id !== queriedRun) continue
      if (current.status === 'applied' && current.applied_artifact_id && current.apply_run_id === queriedRun) break
      if (run.status === 'succeeded') {
        if (current.status !== 'applying') throw new Error('尚未确认正式结果发布，请重新查询应用结果。')
        await new Promise(resolve => setTimeout(resolve, 1000))
        if (!isCurrent(version, id)) return null
        continue
      }
      if (run.status === 'failed' || run.status === 'cancelled') {
        applyReceipts.current.delete(current.id)
        await refreshActive(id)
        throw Object.assign(new Error(run.error_message || '修改未应用，草稿和旧正式结果已保留。'), { mappingDraft: current })
      }
      if (current.status !== 'applying') throw Object.assign(new Error('修改未应用，草稿已恢复，请检查后重试。'), { mappingDraft: current })
      await new Promise(resolve => setTimeout(resolve, 1000))
      if (!isCurrent(version, id)) return null
    }
    if (current.status !== 'applied' || !current.applied_artifact_id) throw new Error('没有可确认的新正式结果，请重新加载草稿。')
    await refreshActive(id)
    return isCurrent(version, id) ? current : null
  }
  const discardDraft = async (current: MappingDraft, version: number) => {
    if (!isCurrent(version, current.conversation_id)) return null
    const next = await api.discardMappingDraft(current.id, current.revision)
    if (!isCurrent(version, current.conversation_id)) return null
    draftChanged(next)
    await refreshActive(current.conversation_id)
    return isCurrent(version, current.conversation_id) ? next : null
  }
  const sendContent = async (id: string, content: string, version: number) => {
    if (!isCurrent(version, id) || editingPendingRef.current) return
    try {
      const sent = await api.sendMessage(id, content)
      if (!isCurrent(version, id)) return
      if (sent.run) setNotice('消息已创建业务任务，执行结果将在会话中显示。')
      setDraft(''); setPendingSend(null); setPendingConfirmation(null); setResolutionError('')
      await refreshActive(id)
      if (isCurrent(version, id) && workspaceTab === 'conversation') { setNewReplies(false); stickToBottom.current = true; requestAnimationFrame(() => scrollConversationToEnd()) }
    } catch (caught) {
      if (!isCurrent(version, id)) return
      if ((caught as ApiError).code === 'draft_resolution_required') {
        const detail = await api.conversation(id)
        if (!isCurrent(version, id)) return
        setConversation(detail)
        setPendingSend({ id, content, version, drafts: unresolvedDrafts(detail.drafts) })
        setResolutionError('还有未应用的修改，请选择如何处理后继续发送。')
      } else if ((caught as ApiError).code === 'field_preview_resolution_required') {
        await refreshActive(id); if (!isCurrent(version, id)) return; setNotice('请先查看字段变更，应用或取消后再发送。')
      } else if ((caught as ApiError).code === 'confirmation_resolution_required') {
        const detail = await api.conversation(id); if (!isCurrent(version, id)) return; setConversation(detail); const run = detail.runs.find(item => item.status === 'waiting_confirmation'); if (run) setPendingConfirmation({id, content, version, run}); else throw caught
      } else throw caught
    }
  }
  const send = async (input?: string) => {
    const content = (input ?? draft).trim(), version = viewToken.current
    if (!content || busy || clearBusy || pendingSend || pendingConfirmation || editingPendingRef.current) return
    if (input) setNotice(`正在发送：${content}`)
    setBusy(true); setError('')
    try {
      const id = await ensureConversation(version)
      if (!id || !isCurrent(version, id)) return
      const remaining = unresolvedDrafts(conversation?.drafts)
      if (remaining.length) { setPendingSend({ id, content, version, drafts: remaining }); setResolutionError(''); return }
      const pendingFields = conversation?.field_changes?.find(item => ['ready', 'applying'].includes(item.status)); if (pendingFields) { setFieldChangesId(pendingFields.run_id); setNotice('消息尚未发送，请先处理当前字段变更。'); return }
      const waiting = conversation?.runs.find(run => run.status === 'waiting_confirmation'); if (waiting) { setPendingConfirmation({id, content, version, run: waiting}); return }
      await sendContent(id, content, version)
    } catch (caught) { if (isCurrent(version)) { if (input) setDraft(current => current || content); setError(caught instanceof Error ? caught.message : '消息发送失败。') } }
    finally { if (isCurrent(version)) setBusy(false) }
  }
  const resolveSend = async (choice: 'apply' | 'discard') => {
    if (!pendingSend || busy || resolutionConflict) return
    const { id, content, version } = pendingSend
    const target = pendingSend.drafts[0]
    if (!target || !isCurrent(version, id)) return
    setBusy(true); setResolutionError('')
    try {
      const current = await api.mappingDraft(target.id)
      if (!isCurrent(version, id)) return
      if (current.id !== target.id || current.conversation_id !== id || current.conversation_id !== target.conversation_id || current.base_artifact_id !== target.base_artifact_id || current.revision !== target.revision) {
        throw Object.assign(new Error('草稿已更新，已停止处理。请重新加载草稿状态后确认。'), { code: 'draft_revision_conflict' })
      }
      if (current.status === 'active' || current.status === 'applying') {
        const resolved = choice === 'apply' ? await applyAndWait(current, version) : await discardDraft(current, version)
        if (!resolved || !isCurrent(version, id)) return
      }
      const detail = await api.conversation(id)
      if (!isCurrent(version, id)) return
      setConversation(detail)
      const remaining = unresolvedDrafts(detail.drafts)
      if (remaining.length) setPendingSend({ id, content, version, drafts: remaining })
      else { setPendingSend({ id, content, version, drafts: [] }); setMappingId(null); setMappingDraftId(undefined); await sendContent(id, content, version) }
    } catch (caught) { if (isCurrent(version, id)) { setResolutionError(caught instanceof Error ? caught.message : '草稿处理失败，消息尚未发送。'); if ((caught as ApiError).code === 'draft_revision_conflict') setResolutionConflict(true) } }
    finally { if (isCurrent(version, id)) setBusy(false) }
  }
  const reloadResolution = async () => {
    if (!pendingSend || busy) return
    const { id, content, version } = pendingSend
    setBusy(true)
    try {
      const detail = await api.conversation(id)
      if (!isCurrent(version, id)) return
      setConversation(detail); setPendingSend({ id, content, version, drafts: unresolvedDrafts(detail.drafts) }); setResolutionError(''); setResolutionConflict(false)
    } catch (caught) { if (isCurrent(version, id)) setResolutionError(caught instanceof Error ? caught.message : '草稿状态加载失败。') }
    finally { if (isCurrent(version, id)) setBusy(false) }
  }
  const returnToEditing = () => {
    if (!pendingSend || busy) return
    const next = pendingSend.drafts[0]
    setPendingSend(null); setResolutionError(''); setResolutionConflict(false)
    if (next) { setMappingId(next.base_artifact_id); setMappingDraftId(next.id) }
  }
  const clearBusiness = async () => {
    if (!activeId || identity?.role !== 'user' || clearBusy || busy) return
    if (!window.confirm('清空当前业务数据将取消活动执行和待确认事项、丢弃未应用草稿。历史文件与结果仍可查看和下载，未发送文本会保留。确认清空？')) return
    const version = viewToken.current, id = activeId
    if (clearReceipt.current?.id !== id) clearReceipt.current = {id, key: crypto.randomUUID()}
    setClearBusy(true); setClearError('')
    try {
      await api.sendMessage(id, '清空数据', clearReceipt.current.key)
      if (!isCurrent(version, id)) return
      setPendingSend(null); setPendingConfirmation(null); setResolutionError(''); setResolutionConflict(false)
      setMappingId(null); setMappingDraftId(undefined); setMappingSource(null); setEditingPending(false); editingPendingRef.current = false
      setNotice('清空业务数据已排队，历史结果和未发送文本会保留。')
      await refreshActive(id)
      if (isCurrent(version, id)) clearReceipt.current = null
    } catch (caught) {if (isCurrent(version, id)) setClearError(caught instanceof Error ? caught.message : '清空未能启动，业务数据和未发送文本已保留。')}
    finally {if (isCurrent(version, id)) setClearBusy(false)}
  }
  const upload = async (file: File) => {
    if (clearBusy) return
    const version = viewToken.current
    setBusy(true); setError('')
    try {
      const id = await ensureConversation(version)
      if (!id || !isCurrent(version, id)) return
      if (uploadRole === 'enum_mapping') await api.uploadFile(id, file, uploadRole)
      else await api.uploadFile(id, file)
      if (!isCurrent(version, id)) return
      setNotice('文件已上传，正在校验。')
      await refreshActive(id)
    } catch (caught) { if (isCurrent(version)) setError(caught instanceof Error ? caught.message : '上传失败，请检查文件后重试。') }
    finally { if (isCurrent(version)) { setBusy(false); if (fileInput.current) fileInput.current.value = '' } }
  }
  const parseLog = async (file: FileRecord) => {
    if (!activeId || actionBusy || file.active === false) return
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
    if (mappingSource.kind === 'file' && conversation?.files.find(file => file.id === mappingSource.id)?.active === false) return
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
    setActiveId(null); resetMapping(); setConversation(null); setNotice(''); setActionBusy(null); setLoading(true)
    setBusy(true); setError('')
    try {
      await api.selectIdentity(userId)
      sessionStorage.removeItem('twa-v2-active')
      setActiveId(null); setConversation(null)
      await initialize()
    } catch (caught) { setError(caught instanceof Error ? caught.message : '切换身份失败。') }
    finally { setBusy(false) }
  }
  const openRun = async (runId: string) => {
    setDiagnosticRunId(null)
    setTraceTarget(current => ({ id: runId, token: (current?.token || 0) + 1 }))
    changeWorkspaceTab('trace')
  }
  const openHistory = async (conversationId: string, runId: string | null, messageId: string | null) => {
    await selectConversation(conversationId)
    if (runId) await openRun(runId)
    else if (messageId) locate(messageId)
  }
  const activeRun = conversation?.runs.find(run => runningStatus.has(run.status))
  const waitingRun = conversation?.runs.find(run => run.status === 'waiting_confirmation' && !conversation?.field_changes?.some(item => item.run_id === run.id))
  const selectedArtifact = conversation?.artifacts?.find(item => item.id === selectedResultId)
  const openArtifact = async (artifact: Artifact) => {
    if (!openResource('results')) return
    setFieldChangesSelection(null)
    const version = viewToken.current; const id = activeViewId.current; const request = ++artifactRequest.current
    setSelectedResultId(artifact.id); setArtifactContent(null); setArtifactError(''); setArtifactLoading(true)
    try { const content = await api.artifactContent(artifact.id); if (request === artifactRequest.current && isCurrent(version, id || undefined)) setArtifactContent(content) }
    catch (caught) { if (request === artifactRequest.current && isCurrent(version, id || undefined)) setArtifactError(caught instanceof Error ? caught.message : '结果加载失败。') }
    finally { if (request === artifactRequest.current && isCurrent(version, id || undefined)) setArtifactLoading(false) }
  }
  const locate = (messageId?: string | null) => { if (messageId) { changeWorkspaceTab('conversation'); requestAnimationFrame(() => document.getElementById('message-' + messageId)?.scrollIntoView?.({block: 'center'})) } }
  const applySuggestion = (suggestion: Suggestion, message: Message) => {
    if (suggestion.type === 'prompt') { setDraft(suggestion.text || ''); return }
    if (suggestion.id === 'log_parse') {
      const file = conversation?.files.find(item => item.id === suggestion.file_id)
      if (file) void parseLog(file)
    } else if (suggestion.id === 'field_mapping') {
      void send('标准字段映射')
    } else if (suggestion.id === 'open_results' || suggestion.id === 'download') {
      const artifact = conversation?.artifacts?.find(item => item.id === suggestion.artifact_id) || conversation?.artifacts?.[(conversation.artifacts?.length || 1) - 1]
      if (!artifact) return
      if (suggestion.id === 'open_results') void openArtifact(artifact)
      else void downloadMapping(artifact.id)
    } else if (suggestion.id === 'retry') {
      if (message.run_id) void retryRun(message.run_id)
    } else if (suggestion.id === 'open_trace') {
      if (message.run_id) void openRun(message.run_id)
    }
  }
  const businessCard = (artifact: Artifact) => <article className="result-card ledger-row" key={artifact.id}><strong>{businessName(artifact.kind)}结果</strong>{(artifact.kind === 'enum_values' || artifact.kind === 'threat_mapping' || artifact.kind === 'config_export') && <p>{artifact.item_count ?? (typeof artifact.summary?.item_count === 'number' ? artifact.summary.item_count : 0)} 项</p>}{'current' in artifact && !artifact.current && <p className="mapping-warning">历史结果，可查看和下载。</p>}<div className="mapping-actions"><button className="button-secondary" onClick={() => void openArtifact(artifact)}>查看产物</button>{artifact.kind === 'field_mapping' && <button className="button-secondary" onClick={() => {if (setMappingId(artifact.id)) setMappingDraftId(undefined); setSelectedResultId(null)}}>查看结果</button>}<button className="button-secondary" onClick={() => void downloadMapping(artifact.id)} disabled={!!downloadId}>下载产物</button></div>{downloadError?.id === artifact.id && <p className="mapping-error" role="alert">{downloadError.message}</p>}</article>
  const mappingSummary = (artifact: FieldMappingArtifact) => { const draft = conversation?.drafts?.find(item => item.base_artifact_id === artifact.id && ['active', 'applying'].includes(item.status)); return <MappingSummaryCard key={identity?.id + ':' + activeId + ':' + artifact.id} artifact={artifact} editable={identity?.role === 'user'} draftId={draft?.id} draftSummary={draft} onDraftChange={draftChanged} onPendingChange={pendingChanged} onOpenFull={() => { if (setMappingId(artifact.id)) { setMappingDraftId(undefined); resourceTrigger.current = document.getElementById('mapping-' + artifact.id)?.querySelector('button') || null } }} onOpenDrawer={() => void openArtifact(artifact)} onDownload={() => void downloadMapping(artifact.id)} downloading={downloadId === artifact.id} downloadError={downloadError?.id === artifact.id ? downloadError.message : ''} /> }
  const liveDrafts = unresolvedDrafts(conversation?.drafts)
  const fieldChange = conversation?.field_changes?.find(item => item.run_id === fieldChangesId)
  const mappingArtifact = conversation?.artifacts?.find((artifact): artifact is FieldMappingArtifact => artifact.kind === 'field_mapping' && artifact.id === mappingId)
  const classificationCard = (artifact: ClassificationArtifact) => {
    const identityKey = identity?.id + ':' + activeId + ':' + artifact.id
    return <LogClassificationCard key={identityKey} artifact={artifact} identityKey={identityKey} actions={<>
      <div className="mapping-actions"><button className="button-secondary" onClick={() => void openArtifact(artifact)}>查看产物</button><button className="button-secondary" onClick={() => void downloadMapping(artifact.id)} disabled={!!downloadId}>下载产物</button></div>
      {downloadError?.id === artifact.id && <p className="mapping-error" role="alert">{downloadError.message}</p>}
      {identity?.role === 'user' && artifact.mapping_eligible && <details><summary>导出解析规则</summary><BusinessOperations key={identityKey + ':ops'} conversation={conversation!} source={artifact} onDone={() => refreshActive(conversation!.id)} /></details>}
      {artifact.submission_status && <p role="status">申请状态：{{ created: '待审核', pending_duplicate: '已有待审核申请', already_approved: '已批准', stale: '结果已过期', error: '提交失败' }[artifact.submission_status] || statusName[artifact.submission_status] || artifact.submission_status}{artifact.application_id ? '（申请编号 ' + artifact.application_id + '）' : ''}</p>}
      {identity?.role === 'user' && artifact.submission_eligible && (!artifact.submission_status || artifact.submission_status === 'error') && <button className="button-secondary" onClick={() => void submitKnowledge(artifact)} disabled={!!actionBusy}>{actionBusy === artifact.id ? '提交中…' : '申请加入知识库'}</button>}
      {identity?.role === 'user' && artifact.mapping_eligible && <><button className="button-secondary" onClick={() => setMappingSource({ id: artifact.id, kind: 'classification', label: '日志分类结果' })} disabled={!!actionBusy}>标准字段映射</button>{mappingForm({ id: artifact.id, kind: 'classification', label: '日志分类结果' })}</>}
    </>} />
  }
  const timelineActions: TimelineActions = {
    onOpenRun: id => { void openRun(id) },
    onParseLog: file => { void parseLog(file) },
    onFeatureField: (id, value) => setFeatureFields(current => ({ ...current, [id]: value })),
    featureFields,
    actionBusy,
    onMappingSource: source => setMappingSource(source),
    mappingForm,
    onOpenFieldChanges: runId => { if (openResource('results')) setFieldChangesId(runId) },
    onSuggestion: applySuggestion,
    canOperate: identity?.role === 'user',
  }
  const paramPrompt = (() => {
    if (!conversation || identity?.role !== 'user') return null
    const lastReply = [...conversation.messages].reverse().find(message => message.actor === 'assistant')
    if (!lastReply?.run_id || dismissedParamRuns.includes(lastReply.run_id)) return null
    const run = conversation.runs.find(item => item.id === lastReply.run_id)
    if (!run || run.error_code !== 'data_source_fields_required' || !run.file_id) return null
    const label = conversation.files.find(file => file.id === run.file_id)?.name || '当前主数据'
    return { message: lastReply, run, source: { id: run.file_id, kind: 'file' as const, label } }
  })()
  const timelineRenderers = {
    mappingSummary,
    businessCard,
    classificationCard,
    paramsForm: (message: Message) => {
      if (!paramPrompt || paramPrompt.message.id !== message.id) return null
      return <div className="params-form-card" role="group" aria-label="补充标准字段映射参数">
        <span className="params-form-tag">需要你补充</span>
        <MappingForm source={paramPrompt.source} submitting={actionBusy === paramPrompt.source.id} onSubmit={fields => submitInlineMapping(paramPrompt.source, fields)} onCancel={() => setDismissedParamRuns(current => [...current, paramPrompt.run.id])} />
      </div>
    },
  }
  const latestRun = conversation?.runs.at(-1)
  const hintedRun = waitingRun || activeRun || (latestRun?.status === 'failed' ? latestRun : undefined)
  const hintState = hintedRun?.status === 'waiting_confirmation' ? 'waiting_confirmation' : hintedRun?.status === 'failed' ? 'failed' : hintedRun ? 'running' : null
  const openResult = (artifact: Artifact) => {
    void openArtifact(artifact)
  }
  if (identity?.role === 'admin') return <AdminConsole identity={identity} identities={identities} onSwitchIdentity={id => void switchIdentity(id)} theme={theme} onToggleTheme={() => setTheme(theme === 'light' ? 'dark' : 'light')} />
  if (identity?.role === 'developer' && developerDiagnostics) return <DeveloperConsole identity={identity} identities={identities} onSwitchIdentity={id => void switchIdentity(id)} onBack={() => setDeveloperDiagnostics(false)} theme={theme} onToggleTheme={() => setTheme(theme === 'light' ? 'dark' : 'light')} />
  return <div className="app">
    <button className="mobile-nav-toggle" onClick={() => setNavOpen(!navOpen)} aria-label="切换导航"><span aria-hidden="true">☰</span></button>
    <aside className={'sidebar ' + (navOpen ? 'sidebar-open' : '')}>
      <div className="brand"><span className="brand-mark">T</span><span>ToolWithAgent <small>V2 工作台</small></span></div>
      <button className="new-conversation" onClick={() => void createConversation()} disabled={busy}>＋ 新会话</button>
      <nav aria-label="会话导航"><button className={"nav-item " + (workspaceTab === 'conversation' || workspaceTab === 'trace' ? 'selected' : '')} onClick={() => changeWorkspaceTab('conversation')}>当前会话</button><details className="history-nav"><summary>历史记录</summary><button className="nav-item" onClick={() => changeWorkspaceTab('tasks')}>我的任务</button><button className="nav-item" onClick={() => changeWorkspaceTab('runs')}>我的执行</button></details>{identity?.role === 'developer' && <button className="nav-item" onClick={() => setDeveloperDiagnostics(true)}>Run 诊断</button>}</nav>
      <div className="recent-title">最近会话</div>
      <div className="recent-list">{conversations.length ? conversations.map(item => <button key={item.id} className={'recent-item ' + (item.id === activeId ? 'active' : '')} onClick={() => void selectConversation(item.id)}><span className="recent-name">{item.title || '未命名会话'}</span><span className="recent-meta"><span className="recent-time">{readableTime(item.updated_at)}</span>{item.latest_run_status && <StatusText status={item.latest_run_status} />}</span></button>) : <p className="sidebar-empty">新建会话开始工作</p>}</div>
      <div className="identity">
        <div className="identity-head">
          <span className="avatar">{identity?.display_name?.slice(0, 1) || '用'}</span>
          <span className="identity-name">{identity?.display_name || '加载中'}<small>{identity?.role || 'user'}</small></span>
        </div>
        {identities.length > 0 && <select aria-label="开发身份切换" value={identity?.id || ''} onChange={event => void switchIdentity(event.target.value)} disabled={busy}>{identities.map(item => <option key={item.id} value={item.id}>{item.display_name} ({item.role})</option>)}</select>}
      </div>
    </aside>
    <main className="workspace">
      <header className="workspace-header"><div className="workspace-title"><h1>{workspaceTab === 'tasks' ? '我的任务' : workspaceTab === 'runs' ? '我的执行' : conversation?.title || '工作台'}</h1>{conversation && !renaming && <button className="button-text rename-trigger" aria-label="重命名会话" onClick={() => { setTitleDraft(conversation.title); setRenaming(true) }}>✎ 重命名</button>}{renaming && conversation && <><input aria-label="会话名称" autoFocus className="rename-input" value={titleDraft} onChange={event => { setTitleDraft(event.target.value) }} onKeyDown={event => { if (event.key === 'Enter') void submitRename(); if (event.key === 'Escape') setRenaming(false) }} /><button className="button-text" onClick={() => void submitRename()}>保存</button><button className="button-text" onClick={() => setRenaming(false)}>取消</button></>}<p>{conversation ? '会话与执行状态' : '从一条消息或一个文件开始'}</p></div><div className="header-actions">{conversation && <button className="button-text" onClick={() => { setSelectedResultId(null); openResource('results') }}>结果与产物</button>}{identity?.role === 'user' && activeId && <button className="button-text" onClick={() => void clearBusiness()} disabled={clearBusy || busy || loading}>{clearBusy ? '清空排队中…' : '清空业务数据（保留历史）'}</button>}{conversation && !resourceOpen && resourceTabs.length > 0 && <button className="button-secondary" onClick={() => { setResourceOpen(true); changeWorkspaceTab('conversation') }}>打开工作区</button>}<button className="icon-button" aria-label={theme === 'light' ? '切换深色主题' : '切换浅色主题'} title={theme === 'light' ? '切换深色主题' : '切换浅色主题'} onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>{theme === 'light' ? '深色主题' : '浅色主题'}</button></div></header>
      <div className="workspace-tabs" role="tablist" aria-label="工作区视图" onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        const tabs = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role=tab]')]
        const index = tabs.indexOf(document.activeElement as HTMLButtonElement)
        if (index < 0) return
        event.preventDefault()
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length
        tabs[next]?.click(); tabs[next]?.focus()
      }}>{([['conversation', '对话'], ['trace', '轨迹']] as const).map(([id, label]) => <button key={id} role="tab" aria-selected={workspaceTab === id} tabIndex={workspaceTab === id ? 0 : -1} onClick={() => changeWorkspaceTab(id)}>{label}</button>)}<span className="workspace-task-status">{(hintedRun || latestRun) && <StatusText status={(hintedRun || latestRun)!.status} />}{liveDrafts.length > 0 && <span>{liveDrafts.reduce((sum, item) => sum + item.changed_count, 0)} 处草稿修改</span>}</span></div>
      {error && <div role="alert" className="feedback error"><span>{error}</span><button onClick={() => { setError(''); void initialize() }}>重试</button></div>}
      {clearError && <div role="alert" className="feedback error">{clearError}</div>}
      {notice && <div role="status" className="feedback notice"><span>{notice}</span><button aria-label="关闭提示" onClick={() => setNotice('')}>关闭</button></div>}
      <div className="conversation-layout" ref={layoutRef}>
      <div className="conversation-main">
      <div className={'conversation-content' + (workspaceTab === 'trace' ? ' trace-view' : '')} ref={contentRef} onScroll={onConversationScroll}>
        {(workspaceTab === 'tasks' || workspaceTab === 'runs') && <div className="workbench-pane"><UserHistory key={identity?.id + ':' + workspaceTab} kind={workspaceTab} onOpen={(conversationId, runId, messageId) => { void openHistory(conversationId, runId, messageId) }} /></div>}
        <div className="workbench-pane conversation-pane" hidden={workspaceTab !== 'conversation'}>{loading ? <div className="empty-state"><h2>正在加载工作台…</h2></div> : !conversation ? <div className="empty-state"><h2>从一句话或一个文件开始</h2><p>也可以从常见场景进入——点击填入话术，可自行修改或拼接多步。</p><button className="button-primary" onClick={() => fileInput.current?.click()}>上传文件</button><div className="empty-templates">{SCENE_TEMPLATES.map(template => <button key={template.title} type="button" className="empty-template" onClick={() => setDraft(template.prompt)}><strong>{template.title}</strong><span>{template.hint}</span></button>)}</div></div> : <>
          <ConversationTimeline conversation={conversation} actions={timelineActions} renderers={timelineRenderers} />
          {conversation.session_facts_error && <p className="mapping-error" role="alert">当前业务输入不可用，历史结果仍可查看。请重新加载或上传主数据。</p>}
          {identity?.role === 'user' && liveDrafts.length > 0 && <section className="activity-section"><h2>未应用的映射草稿</h2>{liveDrafts.map(item => <article className="result-card" key={item.id}><p>{item.changed_count} 处未应用修改{!item.base_current ? ' · 来源已过期' : ''}{item.status === 'applying' ? ' · 正在应用' : ''}</p><button className="button-secondary" onClick={() => { if (setMappingId(item.base_artifact_id)) setMappingDraftId(item.id) }}>恢复草稿</button></article>)}</section>}
        </>}</div>
        {conversation && visitedTabs.includes('trace') && <div className="workbench-pane" hidden={workspaceTab !== 'trace'}>{diagnosticRunId ? <RunDiagnostics key={diagnosticRunId} initialRunId={diagnosticRunId} userMode onClose={() => setDiagnosticRunId(null)} /> : <TrajectoryLedger key={identity?.id + ':' + activeId} conversation={conversation} onOpen={openResult} onDetails={setDiagnosticRunId} targetId={traceTarget?.id} targetToken={traceTarget?.token} onRetry={id => void retryRun(id)} onStop={id => void stopRun(id)} canOperate={identity?.role === 'user'} busy={!!actionBusy} />}</div>}
      </div>
      {newReplies && workspaceTab === 'conversation' && <div className="new-replies-bar"><button className="button-secondary" onClick={() => { setNewReplies(false); stickToBottom.current = true; requestAnimationFrame(() => scrollConversationToEnd('smooth')) }}>有新回复 · 点击查看</button></div>}
      <div className="composer-region" hidden={workspaceTab !== "conversation"}><TaskHintBar state={hintState} status={hintedRun?.status} title={hintedRun ? businessName(hintedRun.kind || '') : ''} description={latestProgress && hintedRun && latestProgress.runId === hintedRun.id ? (hintedRun.status === 'running' && latestProgress.summary.phase === 'completed' ? '正在整理并发布结果' : progressLabel(latestProgress.summary)) : undefined}>
        {hintedRun && <button className="button-text" onClick={() => void openRun(hintedRun.id)}>{hintState === 'failed' ? '查看失败原因' : '查看执行详情'}</button>}
        {activeRun && hintedRun?.id === activeRun.id && identity?.role === 'user' && <button className="button-text" onClick={() => void stopRun(activeRun.id)} disabled={!!actionBusy}>停止</button>}
      </TaskHintBar>
        {waitingRun && !pendingConfirmation && identity?.role === 'user' && <BusinessConfirmation key={identity.id + ':' + activeId + ':' + waitingRun.id} run={waitingRun} onBack={() => {void openRun(waitingRun.id)}} onResolved={() => refreshActive(activeId!)} />}
        {editingPending && <p className="mapping-hint composer-draft-hint" role="status">请先完成草稿保存或确认，再发送消息。</p>}<div className="composer"><textarea aria-label="消息内容" placeholder="描述要处理的日志、字段或规则…" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} rows={2} disabled={busy || clearBusy || loading || !!pendingSend || !!pendingConfirmation} /><div className="composer-toolbar"><div><label>上传用途<select aria-label="上传用途" value={uploadRole} onChange={event => setUploadRole(event.target.value as typeof uploadRole)} disabled={busy || clearBusy || loading}><option value="primary">日志或规则主数据</option><option value="enum_mapping">枚举映射附件</option></select></label><input accept={uploadRole === 'enum_mapping' ? '.xlsx' : undefined} ref={fileInput} type="file" hidden aria-label="选择文件" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file) }} /><button className="attach-button" onClick={() => fileInput.current?.click()} disabled={busy || clearBusy || loading}>＋ 添加文件</button><span className="composer-hint">Enter 发送 · Shift+Enter 换行</span></div><button className="button-primary send-button" onClick={() => void send()} disabled={!draft.trim() || busy || clearBusy || loading || editingPending || !!pendingSend || !!pendingConfirmation}>{busy ? '处理中…' : '发送'}</button></div></div>
      </div>
      </div>
      {resourceTabs.length > 0 && <>
        <div className="resource-divider" role="separator" aria-label="调整工作区宽度" aria-orientation="vertical" aria-valuemin={480} aria-valuemax={Math.max(480, (layoutRef.current?.clientWidth || 1200) - 360)} aria-valuenow={resourceWidth ?? Math.round((layoutRef.current?.clientWidth || 1200) * .55)} aria-valuetext={`工作区宽度 ${resourceWidth ?? Math.round((layoutRef.current?.clientWidth || 1200) * .55)} 像素`} tabIndex={resourceOpen && workspaceTab === 'conversation' ? 0 : -1} hidden={!resourceOpen || workspaceTab !== 'conversation'} onPointerDown={event => event.currentTarget.setPointerCapture?.(event.pointerId)} onPointerMove={event => { if (event.buttons !== 1 || !layoutRef.current) return; const width = layoutRef.current.getBoundingClientRect().right - event.clientX; setResourceWidth(Math.max(480, Math.min(width, layoutRef.current.clientWidth - 360))) }} onKeyDown={event => { if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return; event.preventDefault(); const width = resourceWidth ?? Math.round((layoutRef.current?.clientWidth || 1200) * .55); setResourceWidth(Math.max(480, Math.min(width + (event.key === 'ArrowLeft' ? 24 : -24), (layoutRef.current?.clientWidth || 1200) - 360))) }} />
        <aside className="resource-workspace" aria-label="资源工作区" hidden={!resourceOpen || workspaceTab !== 'conversation'} style={{ width: resourceWidth == null ? '55%' : resourceWidth }}>
          <header className="resource-header"><div role="tablist" aria-label="资源页签">{resourceTabs.map(tab => <div className="resource-tab" key={tab}><button role="tab" data-resource-tab={tab} aria-selected={activeResource === tab} tabIndex={activeResource === tab ? 0 : -1} onClick={() => selectResourceTab(tab)} onKeyDown={event => resourceTabKeyDown(event, tab)}>{tab === 'mapping' ? '字段映射' : '结果／产物'}</button><button aria-label={'关闭' + (tab === 'mapping' ? '字段映射' : '结果／产物') + '页签'} onClick={() => closeResource(tab)}>×</button></div>)}</div><button className="button-text" onClick={collapseResource}><span className="resource-desktop-label">收起工作区</span><span className="resource-mobile-label">返回对话</span></button></header>
          <div className="resource-pane" hidden={activeResource !== 'mapping'}>{mappingArtifact && <MappingWorkspace key={identity?.id + ':' + activeId + ':' + mappingArtifact.id} artifact={mappingArtifact} onBack={collapseResource} onDownload={() => void downloadMapping(mappingArtifact.id)} downloading={downloadId === mappingArtifact.id} downloadError={downloadError?.id === mappingArtifact.id ? downloadError.message : ''} editable={identity?.role === 'user'} draftId={mappingDraftId || conversation?.drafts?.find(item => item.base_artifact_id === mappingArtifact.id && ['active', 'applying'].includes(item.status))?.id} onDraftChange={draftChanged} onPendingChange={pendingChanged} onApply={current => applyAndWait(current, viewToken.current)} onDiscard={current => discardDraft(current, viewToken.current)} />}</div>
          <div className="resource-pane" hidden={activeResource !== 'results'}>{fieldChange && !loading ? <FieldChangesWorkspace key={identity?.id + ':' + activeId + ':' + fieldChange.run_id} summary={fieldChange} editable={identity?.role === 'user'} onBack={() => { setFieldChangesId(null); collapseResource() }} onRefresh={() => refreshActive(activeId!)} onExecution={id => { void openRun(id) }} /> : <section aria-label="结果与产物"><h2>结果与产物</h2><div className="resource-artifact-list">{conversation?.artifacts?.map(item => <button key={item.id} className={item.id === selectedResultId ? 'selected' : ''} onClick={() => void openArtifact(item)}>{businessName(item.kind)} · 版本 {item.version ?? '未记录'}{'current' in item && !item.current ? ' · 历史' : ''}</button>)}{!conversation?.artifacts?.length && <p>当前会话还没有已发布产物。</p>}</div>{selectedArtifact && <article className="resource-artifact-detail"><h3>{businessName(selectedArtifact.kind)} · 版本 {selectedArtifact.version ?? '未记录'}</h3><p>{selectedArtifact.status === 'corrupt' ? '产物不可用' : selectedArtifact.status === 'stale' || ('current' in selectedArtifact && !selectedArtifact.current) ? '历史结果' : selectedArtifact.status === 'published' ? '已发布' : '状态不可用'}</p><p>来源 Run：<button className="button-text" onClick={() => void openRun(selectedArtifact.run_id)}>{selectedArtifact.run_id}</button></p>{artifactLoading && <p role="status">正在加载结果…</p>}{artifactError && <p role="alert">{artifactError}<button className="button-text" onClick={() => void openArtifact(selectedArtifact)}>重试</button></p>}{artifactContent && <ArtifactValues artifact={selectedArtifact} content={artifactContent} />}<button className="button-secondary" onClick={() => void downloadMapping(selectedArtifact.id)} disabled={!!downloadId}>下载产物</button>{downloadError?.id === selectedArtifact.id && <p role="alert">{downloadError.message}</p>}</article>}</section>}</div>
        </aside>
      </>}
      </div>
    </main>
    {pendingConfirmation && <MappingDialog title="发送前处理执行方案" onClose={() => setPendingConfirmation(null)}><BusinessConfirmation key={identity?.id + ':' + activeId + ':' + pendingConfirmation.run.id + ':send'} run={pendingConfirmation.run} beforeSend onBack={() => setPendingConfirmation(null)} onResolved={async () => {const pending = pendingConfirmation; if (!isCurrent(pending.version, pending.id)) return; await refreshActive(pending.id); if (isCurrent(pending.version, pending.id)) await sendContent(pending.id, pending.content, pending.version)}} /></MappingDialog>}

    {pendingSend && <MappingDialog title="发送前处理映射草稿" onClose={returnToEditing}><p>消息尚未发送。请处理{pendingSend.drafts.length > 1 ? '当前草稿，再逐个处理其余草稿' : '未应用的修改'}。</p>{pendingSend.drafts[0] && <p>{pendingSend.drafts[0].changed_count} 处修改{!pendingSend.drafts[0].base_current ? '，来源已过期，只能丢弃或返回查看' : ''}。</p>}{resolutionError && <p role="alert" className="mapping-error">{resolutionError}</p>}<div className="mapping-actions"><button className="button-text" data-dialog-cancel onClick={returnToEditing} disabled={busy}>返回编辑</button>{pendingSend.drafts.length ? <><button className="button-text" onClick={() => void resolveSend('apply')} disabled={busy || resolutionConflict || !pendingSend.drafts[0].base_current}>应用后发送</button><button className="button-text" onClick={() => void resolveSend('discard')} disabled={busy || resolutionConflict || pendingSend.drafts[0].status === 'applying'}>丢弃后发送</button></> : <button className="button-text" onClick={() => { const pending = pendingSend; setPendingSend(null); setBusy(true); void sendContent(pending.id, pending.content, pending.version).catch(caught => { if (isCurrent(pending.version, pending.id)) setError(caught instanceof Error ? caught.message : '消息发送失败。') }).finally(() => { if (isCurrent(pending.version, pending.id)) setBusy(false) }) }}>继续发送</button>}<button className="button-text" onClick={() => void reloadResolution()} disabled={busy}>重新加载草稿状态</button></div></MappingDialog>}
  </div>
}
