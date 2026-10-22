import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api, saveDownload, type ClassificationArtifact, type Conversation, type ConversationSummary, type FieldMappingArtifact, type FileRecord, type Identity, type MappingInput, type MappingDraft, type MappingDraftSummary, type ApiError, type Artifact, type Run, type ProgressSummary } from './api'
import { TaskOverview, ResultsWorkspace, ExecutionTrace, type WorkspaceTab } from './WorkspaceViews'
import { ContextPanel, StatusText, TaskHintBar, type PanelState } from './VisualPrimitives'
import { FieldChangesWorkspace } from './FieldChangesWorkspace'
import { MappingWorkspace } from './MappingWorkspace'
import { MappingSummaryCard } from './ConversationMappingSummary'
import { MappingDialog } from './MappingDialog'
import { BusinessOperations, BusinessConfirmation, businessName, ArtifactValues, RunProgress, progressLabel } from './BusinessWorkspace'

const statusName: Record<string, string> = {
  queued: '排队中', pending: '排队中', running: '运行中', succeeded: '已完成',
  waiting_confirmation: '待确认', completed: '已完成', failed: '失败', cancelled: '已取消'
}
const runName = (kind?: string) => ({field_change_apply: '应用字段变更', field_change_undo: '撤销字段变更', business_clear: '清空业务数据', user_request: '业务任务', business_operation: '业务处理', mapping_draft_apply: '应用映射修改', field_mapping: '标准字段映射', log_parse: '日志类型提取', log_knowledge_submit: '日志知识申请'}[kind || ''] || '文件校验')
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
  const [visitedTabs, setVisitedTabs] = useState<WorkspaceTab[]>(['conversation'])
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>('conversation')
  const [resultTarget, setResultTarget] = useState<{ id: string; token: number } | null>(null)
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
  const drawerActive = useRef<string | null>(null)
  const [latestProgress, setLatestProgress] = useState<{runId: string; summary: ProgressSummary} | null>(null)
  const runRequest = useRef(0)
  const [runDetail, setRunDetail] = useState<Run | null>(null)
  const [runDetailError, setRunDetailError] = useState('')
  const artifactRequest = useRef(0)
  const [panel, setPanel] = useState<PanelState>(null)
  const artifactDrawer = panel?.type === 'artifact' ? panel.id : null
  const drawerId = panel?.type === 'execution' ? panel.id : null
  const setArtifactDrawer = (id: string | null) => setPanel(current => id ? { type: 'artifact', id } : current?.type === 'artifact' ? null : current)
  const setDrawerId = (id: string | null) => setPanel(current => id ? { type: 'execution', id } : current?.type === 'execution' ? null : current)
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

  const changeWorkspaceTab = useCallback((next: WorkspaceTab) => {
    if (contentRef.current) viewScroll.current[currentTab.current] = contentRef.current.scrollTop
    setVisitedTabs(current => current.includes(next) ? current : [...current, next]); setWorkspaceTab(next); setPanel(null)
  }, [])
  const setMappingId = useCallback((id: string | null) => { if (editingPendingRef.current && id !== mappingId) { setNotice('请先重试保存或取消当前字段修改。'); return false } setMappingSelection(id); if (id) { setResultTarget(previous => ({ id, token: (previous?.token || 0) + 1 })); changeWorkspaceTab('results') } return true }, [changeWorkspaceTab, mappingId])
  const setFieldChangesId = (id: string | null) => { if (editingPendingRef.current && id) { setNotice('请先重试保存或取消当前字段修改。'); return } setFieldChangesSelection(id) }
  useLayoutEffect(() => { if (contentRef.current) contentRef.current.scrollTop = viewScroll.current[workspaceTab] || 0; currentTab.current = workspaceTab }, [workspaceTab])
  useEffect(() => { if (mappingId || fieldChangesId) changeWorkspaceTab('results') }, [mappingId, fieldChangesId, changeWorkspaceTab])
  drawerActive.current = drawerId
  useEffect(() => {
    if (mappingId || !returnTarget.current) return
    const card = document.getElementById('mapping-' + returnTarget.current)
    card?.scrollIntoView?.({ block: 'center' })
    card?.querySelector<HTMLButtonElement>('button')?.focus()
    returnTarget.current = null
  }, [mappingId])
  const resetMapping = () => { changeWorkspaceTab('conversation'); setVisitedTabs(['conversation']); setResultTarget(null); viewScroll.current = {}; setFieldChangesId(null); clearReceipt.current = null; setClearBusy(false); setClearError(''); setLatestProgress(null); ++runRequest.current; setRunDetail(null); setRunDetailError(''); ++artifactRequest.current; setArtifactDrawer(null); setArtifactContent(null); setArtifactError(''); setArtifactLoading(false); setPendingConfirmation(null); setMappingDraftId(undefined); setEditingPending(false); editingPendingRef.current = false; setPendingSend(null); setResolutionError(''); setResolutionConflict(false); setMappingId(null); setMappingSource(null); setDownloadId(null); setDownloadError(null); mappingReceipt.current = null; returnTarget.current = null }
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
          if (live && version === viewToken.current && record.resource_id && drawerActive.current === record.resource_id) {
              const request = ++runRequest.current; const runId = record.resource_id
              void api.run(runId).then(result => {if (live && version === viewToken.current && request === runRequest.current && drawerActive.current === runId) setRunDetail(result)}).catch(() => {})
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
  const send = async () => {
    const content = draft.trim(), version = viewToken.current
    if (!content || busy || clearBusy || pendingSend || pendingConfirmation || editingPendingRef.current) return
    setBusy(true); setError('')
    try {
      const id = await ensureConversation(version)
      if (!id || !isCurrent(version, id)) return
      const remaining = unresolvedDrafts(conversation?.drafts)
      if (remaining.length) { setPendingSend({ id, content, version, drafts: remaining }); setResolutionError(''); return }
      const pendingFields = conversation?.field_changes?.find(item => ['ready', 'applying'].includes(item.status)); if (pendingFields) { setFieldChangesId(pendingFields.run_id); setNotice('消息尚未发送，请先处理当前字段变更。'); return }
      const waiting = conversation?.runs.find(run => run.status === 'waiting_confirmation'); if (waiting) { setPendingConfirmation({id, content, version, run: waiting}); return }
      await sendContent(id, content, version)
    } catch (caught) { if (isCurrent(version)) setError(caught instanceof Error ? caught.message : '消息发送失败。') }
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
  const openRun = async (runId: string) => {
    const request = ++runRequest.current; const version = viewToken.current
    setArtifactDrawer(null); ++artifactRequest.current; setDrawerId(runId); setRunDetail(null); setRunDetailError('')
    try {const result = await api.run(runId); if (request === runRequest.current && isCurrent(version) && result) setRunDetail(result)}
    catch (caught) {if (request === runRequest.current && isCurrent(version)) setRunDetailError(caught instanceof Error ? caught.message : '执行详情加载失败。')}
  }
  const activeRun = conversation?.runs.find(run => runningStatus.has(run.status))
  const drawer = !artifactDrawer && (runDetail?.id === drawerId ? runDetail : conversation?.runs.find(run => run.id === drawerId)) || null
  const waitingRun = conversation?.runs.find(run => run.status === 'waiting_confirmation' && !conversation?.field_changes?.some(item => item.run_id === run.id))
  const selectedArtifact = conversation?.artifacts?.find(item => item.id === artifactDrawer)
  const openArtifact = async (artifact: Artifact) => {
    const version = viewToken.current; const id = activeViewId.current; const request = ++artifactRequest.current
    setDrawerId(null); setArtifactDrawer(artifact.id); setArtifactContent(null); setArtifactError(''); setArtifactLoading(true)
    try { const content = await api.artifactContent(artifact.id); if (request === artifactRequest.current && isCurrent(version, id || undefined)) setArtifactContent(content) }
    catch (caught) { if (request === artifactRequest.current && isCurrent(version, id || undefined)) setArtifactError(caught instanceof Error ? caught.message : '结果加载失败。') }
    finally { if (request === artifactRequest.current && isCurrent(version, id || undefined)) setArtifactLoading(false) }
  }
  const locate = (messageId?: string | null) => { if (messageId) { changeWorkspaceTab('conversation'); requestAnimationFrame(() => document.getElementById('message-' + messageId)?.scrollIntoView?.({block: 'center'})) } }
  const businessCard = (artifact: Artifact) => <article className="result-card" key={artifact.id}><strong>{businessName(artifact.kind)}结果</strong>{(artifact.kind === 'enum_values' || artifact.kind === 'threat_mapping' || artifact.kind === 'config_export') && <p>{artifact.item_count ?? (typeof artifact.summary?.item_count === 'number' ? artifact.summary.item_count : 0)} 项</p>}{'current' in artifact && !artifact.current && <p className="mapping-warning">历史结果，可查看和下载。</p>}<div className="mapping-actions"><button className="button-secondary" onClick={() => void openArtifact(artifact)}>查看产物</button>{artifact.kind === 'field_mapping' && <button className="button-secondary" onClick={() => {if (setMappingId(artifact.id)) setMappingDraftId(undefined); setArtifactDrawer(null)}}>查看结果</button>}<button className="button-secondary" onClick={() => void downloadMapping(artifact.id)} disabled={!!downloadId}>下载产物</button></div>{downloadError?.id === artifact.id && <p className="mapping-error" role="alert">{downloadError.message}</p>}</article>
  const mappingSummary = (artifact: FieldMappingArtifact) => { const draft = conversation?.drafts?.find(item => item.base_artifact_id === artifact.id && ['active', 'applying'].includes(item.status)); return <MappingSummaryCard key={identity?.id + ':' + activeId + ':' + artifact.id} artifact={artifact} editable={identity?.role === 'user'} draftId={draft?.id} draftSummary={draft} onDraftChange={draftChanged} onPendingChange={pendingChanged} onOpenFull={() => { if (setMappingId(artifact.id)) setMappingDraftId(undefined) }} onOpenDrawer={() => void openArtifact(artifact)} onDownload={() => void downloadMapping(artifact.id)} downloading={downloadId === artifact.id} downloadError={downloadError?.id === artifact.id ? downloadError.message : ''} /> }
  const liveDrafts = unresolvedDrafts(conversation?.drafts)
  const fieldChange = conversation?.field_changes?.find(item => item.run_id === fieldChangesId)
  const mappingArtifact = conversation?.artifacts?.find((artifact): artifact is FieldMappingArtifact => artifact.kind === 'field_mapping' && artifact.id === mappingId)
  const classificationArtifacts = conversation?.artifacts?.filter((artifact): artifact is ClassificationArtifact => artifact.kind === 'log_classification' && ['published', 'stale'].includes(artifact.status)) || []
  const mappingArtifacts = conversation?.artifacts?.filter((artifact): artifact is FieldMappingArtifact => artifact.kind === 'field_mapping' && !(artifact.result_message_id && conversation.messages.some(message => message.id === artifact.result_message_id))) || []
  const latestRun = conversation?.runs.at(-1)
  const hintedRun = waitingRun || activeRun || (latestRun?.status === 'failed' ? latestRun : undefined)
  const hintState = hintedRun?.status === 'waiting_confirmation' ? 'waiting_confirmation' : hintedRun?.status === 'failed' ? 'failed' : hintedRun ? 'running' : null
  const openResult = (artifact: Artifact) => {
    if (artifact.kind !== 'field_mapping' && artifact.kind !== 'log_classification') { void openArtifact(artifact); return }
    changeWorkspaceTab('results')
    if (artifact.kind === 'field_mapping') { if (setMappingId(artifact.id)) setMappingDraftId(undefined) }
    else setResultTarget(previous => ({ id: artifact.id, token: (previous?.token || 0) + 1 }))
  }
  const panelTabs = selectedArtifact ? [
    { id: 'preview', label: '内容预览', content: <><button className="button-text" onClick={() => locate('result_message_id' in selectedArtifact ? selectedArtifact.result_message_id : null)}>定位结果消息</button><button className="button-text" onClick={() => {void openRun(selectedArtifact.run_id)}}>查看执行详情</button>{artifactLoading && <p role="status">正在加载结果…</p>}{artifactError && <p className="mapping-error" role="alert">{artifactError}<button onClick={() => void openArtifact(selectedArtifact)}>重新加载结果</button></p>}{artifactContent && <ArtifactValues artifact={selectedArtifact} content={artifactContent} />}{identity?.role === 'user' && conversation && 'current' in selectedArtifact && selectedArtifact.current && selectedArtifact.kind !== 'config_export' && <BusinessOperations key={identity.id + ':' + activeId + ':' + selectedArtifact.id} conversation={conversation} source={selectedArtifact} onDone={() => refreshActive(conversation.id)} />}</> },
    { id: 'source', label: '来源信息', content: <dl><dt>产物 ID</dt><dd className="num">{selectedArtifact.id}</dd><dt>来源 Run</dt><dd className="num">{selectedArtifact.run_id}</dd><dt>状态</dt><dd>{selectedArtifact.status === 'corrupt' ? '产物不可用' : selectedArtifact.status === 'stale' || ('current' in selectedArtifact && !selectedArtifact.current) ? '历史结果' : selectedArtifact.status === 'published' ? '已发布' : '状态不可用'}</dd></dl> },
  ] : drawer ? [
    { id: 'timeline', label: '执行时间线', content: <>{runDetailError && <p className="mapping-error" role="alert">{runDetailError}</p>}<dl>{drawer.message_id && <><dt>原消息</dt><dd><button className="button-text" onClick={() => locate(drawer.message_id)}>定位消息</button></dd></>}<dt>状态</dt><dd><StatusText status={drawer.status} /></dd><dt>Run ID</dt><dd className="mono">{drawer.id}</dd>{drawer.task_id && <><dt>Task ID</dt><dd className="mono">{drawer.task_id}</dd></>}{drawer.error_code && <><dt>错误代码</dt><dd className="mono">{drawer.error_code}</dd></>}{drawer.error_message && <><dt>原因</dt><dd>{drawer.error_message}</dd></>}</dl><RunProgress run={drawer} />{identity?.role === 'user' && (drawer.status === 'failed' || drawer.status === 'cancelled') && <button className="button-secondary" onClick={() => void retryRun(drawer.id)} disabled={!!actionBusy}>重新执行</button>}<button className="button-secondary" onClick={async () => { try { if (activeId) {await refreshActive(activeId); await openRun(drawer.id)} } catch { setNotice('执行详情刷新失败。') } }}>刷新状态</button></> },
    { id: 'io', label: '输入与输出', content: <dl><dt>执行类型</dt><dd>{runName(drawer.kind)}</dd>{drawer.file_id && <><dt>输入文件 ID</dt><dd className="num">{drawer.file_id}</dd></>}<dt>结果</dt><dd><StatusText status={drawer.status} /></dd>{drawer.message_id && <><dt>原消息</dt><dd><button className="button-text" onClick={() => locate(drawer.message_id)}>定位输入消息</button></dd></>}{conversation?.artifacts?.filter(item => item.run_id === drawer.id).map(item => <div key={item.id} className="context-output"><dt>输出</dt><dd><button className="button-text" onClick={() => void openArtifact(item)}>{businessName(item.kind)}结果</button></dd></div>)}</dl> },
  ] : []
  return <div className="app">
    <button className="mobile-nav-toggle" onClick={() => setNavOpen(!navOpen)} aria-label="切换导航"><span aria-hidden="true">☰</span></button>
    <aside className={'sidebar ' + (navOpen ? 'sidebar-open' : '')}>
      <div className="brand"><span className="brand-mark">T</span><span>ToolWithAgent <small>V2 工作台</small></span></div>
      <button className="new-conversation" onClick={() => void createConversation()} disabled={busy}>＋ 新会话</button>
      <nav aria-label="主导航"><button className={"nav-item " + (workspaceTab !== "trace" ? "selected" : "")} onClick={() => changeWorkspaceTab("conversation")}>对话工作台</button><button className={"nav-item " + (workspaceTab === "trace" ? "selected" : "")} onClick={() => changeWorkspaceTab("trace")}>执行轨迹</button></nav>
      <div className="recent-title">最近会话</div>
      <div className="recent-list">{conversations.length ? conversations.map(item => <button key={item.id} className={'recent-item ' + (item.id === activeId ? 'active' : '')} onClick={() => void selectConversation(item.id)}><span className="recent-name">{item.title || '未命名会话'}</span><span className="recent-time">{readableTime(item.updated_at)}</span></button>) : <p className="sidebar-empty">新建会话开始工作</p>}</div>
      <div className="identity">
        <span className="avatar">{identity?.display_name?.slice(0, 1) || '用'}</span>
        <span className="identity-name">{identity?.display_name || '加载中'}<small>{identity?.role || 'user'}</small></span>
        {identities.length > 0 && <select aria-label="开发身份切换" value={identity?.id || ''} onChange={event => void switchIdentity(event.target.value)} disabled={busy}>{identities.map(item => <option key={item.id} value={item.id}>{item.display_name} ({item.role})</option>)}</select>}
      </div>
    </aside>
    <main className="workspace">
      <header className="workspace-header"><div><h1>{conversation?.title || '工作台'}</h1><p>{conversation ? '会话与执行状态' : '从一条消息或一个文件开始'}</p></div><div className="header-actions">{identity?.role === 'user' && activeId && <button className="button-text" onClick={() => void clearBusiness()} disabled={clearBusy || busy || loading}>{clearBusy ? '清空排队中…' : '清空业务数据（保留历史）'}</button>}<button className="icon-button" aria-label={theme === 'light' ? '切换深色主题' : '切换浅色主题'} title={theme === 'light' ? '切换深色主题' : '切换浅色主题'} onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>{theme === 'light' ? '深色主题' : '浅色主题'}</button></div></header>
      <div className="workspace-tabs" role="tablist" aria-label="工作区视图" onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        const tabs = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role=tab]')]
        const index = tabs.indexOf(document.activeElement as HTMLButtonElement)
        if (index < 0) return
        event.preventDefault()
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length
        tabs[next]?.click(); tabs[next]?.focus()
      }}>{([['conversation', '对话'], ['overview', '任务概览'], ['results', '结果与版本'], ['trace', '执行轨迹']] as const).map(([id, label]) => <button key={id} role="tab" aria-selected={workspaceTab === id} tabIndex={workspaceTab === id ? 0 : -1} onClick={() => changeWorkspaceTab(id)}>{label}</button>)}<span className="workspace-task-status">{(hintedRun || latestRun) && <StatusText status={(hintedRun || latestRun)!.status} />}{liveDrafts.length > 0 && <span>{liveDrafts.reduce((sum, item) => sum + item.changed_count, 0)} 处草稿修改</span>}</span></div>
      {error && <div role="alert" className="feedback error"><span>{error}</span><button onClick={() => { setError(''); void initialize() }}>重试</button></div>}
      {clearError && <div role="alert" className="feedback error">{clearError}</div>}
      {notice && <div role="status" className="feedback notice"><span>{notice}</span><button aria-label="关闭提示" onClick={() => setNotice('')}>关闭</button></div>}
      <div className="conversation-content" ref={contentRef}>
        <div className="workbench-pane" hidden={workspaceTab !== 'conversation'}>{loading ? <div className="empty-state"><h2>正在加载工作台…</h2></div> : !conversation ? <div className="empty-state"><h2>开始一项日志规则任务</h2><p>上传日志或规则文件，或者先描述要处理的内容。</p><button className="button-primary" onClick={() => fileInput.current?.click()}>上传文件</button></div> : <>
          {conversation.messages.length === 0 && conversation.files.length === 0 && <div className="empty-state compact"><h2>这段会话还没有内容</h2><p>发送消息或上传文件，工作台会在这里显示进展。</p></div>}
          <div className="timeline">{conversation.messages.map(message => <article className={'message ' + (message.actor === 'user' ? 'from-user' : '')} key={message.id} id={'message-' + message.id}><div className="message-head"><strong>{message.actor === 'user' ? '你' : 'ToolWithAgent'}</strong><time>{readableTime(message.created_at)}</time></div><p>{message.content}</p>{conversation.artifacts?.filter(artifact => 'result_message_id' in artifact && artifact.result_message_id === message.id).map(artifact => artifact.kind === 'field_mapping' ? mappingSummary(artifact) : businessCard(artifact))}{conversation.field_changes?.filter(item => item.run_id === message.run_id).map(item => <article className="result-card" key={item.run_id}><strong>字段变更</strong><p>{{ready: '待选择与应用', applying: '正在应用', applied: '已应用，可查看或撤销本次变更', undone: '已撤销，历史版本保留', cancelled: '已取消'}[item.status] || item.status}</p><button className="button-secondary" onClick={() => {setMappingId(null); setFieldChangesId(item.run_id)}}>查看变更</button></article>)}{message.run_id && <button className="button-text" onClick={() => {void openRun(message.run_id!)}}>查看本次执行</button>}</article>)}
            {conversation.field_changes?.filter(item => !conversation.messages.some(message => message.run_id === item.run_id)).map(item => <article className="result-card" key={item.run_id}><strong>字段变更</strong><button className="button-secondary" onClick={() => {setMappingId(null); setFieldChangesId(item.run_id)}}>查看变更</button></article>)}
            {conversation.files.length > 0 && <section className="activity-section"><h2>输入文件</h2>{conversation.files.map(file => <div className="file-row" key={file.id}><span className="file-icon">▤</span><div className="file-main"><strong>{file.name}</strong><small>{file.active === false ? '历史输入 · ' : ''}{file.role === 'enum_mapping' ? '枚举映射附件 · ' : '主数据 · '}{file.size != null ? (file.size / 1024).toFixed(1) + ' KB' : '已上传'}</small>{identity?.role === 'user' && file.active !== false && file.role !== 'enum_mapping' && file.parse_status === 'succeeded' && /\.(txt|log|json|jsonl|csv|xlsx)$/i.test(file.name) && <div className="file-actions"><label>分类特征字段（可选）<input aria-label={file.name + ' 分类特征字段'} placeholder="自动识别" value={featureFields[file.id] || ''} onChange={event => setFeatureFields({ ...featureFields, [file.id]: event.target.value })} disabled={!!actionBusy} /></label><button className="button-secondary" onClick={() => void parseLog(file)} disabled={!!actionBusy}>{actionBusy === file.id ? '启动中…' : '提取日志类型'}</button></div>}{identity?.role === 'user' && file.active !== false && file.role !== 'enum_mapping' && file.mapping_eligible && <><button className="button-secondary mapping-entry" onClick={() => setMappingSource({ id: file.id, kind: 'file', label: file.name })} disabled={!!actionBusy}>标准字段映射</button>{mappingForm({ id: file.id, kind: 'file', label: file.name })}</>}</div><StatusText status={file.parse_status || ''} label={statusName[file.parse_status || ''] || '已登记'} className="file-status" /></div>)}</section>}
            {classificationArtifacts.length > 0 && <section className="activity-section"><h2>日志解析结果</h2>{classificationArtifacts.map(artifact => <article className="result-card" key={artifact.id}><div className="result-heading"><strong>日志类型提取完成</strong><span>{readableTime(artifact.created_at)}</span></div><p>覆盖率：{artifact.summary.coverage.matched_lines} / {artifact.summary.coverage.total_lines}</p><div className="result-types">{artifact.summary.log_types.map((item, index) => <span key={item.name + index}>{item.name} · {item.count}</span>)}</div><p className="rule-summary">解析规则：{artifact.summary.rule_summary}</p>{artifact.status === 'stale' && <p className="mapping-warning">历史结果，可查看和下载。</p>}<div className="mapping-actions"><button className="button-secondary" onClick={() => void openArtifact(artifact)}>查看产物</button><button className="button-secondary" onClick={() => void downloadMapping(artifact.id)} disabled={!!downloadId}>下载产物</button></div>{downloadError?.id === artifact.id && <p className="mapping-error" role="alert">{downloadError.message}</p>}{identity?.role === 'user' && artifact.mapping_eligible && <details><summary>导出解析规则</summary><BusinessOperations key={identity.id + ':' + activeId + ':' + artifact.id} conversation={conversation} source={artifact} onDone={() => refreshActive(conversation.id)} /></details>}{artifact.submission_status && <p role="status">申请状态：{{ created: '待审核', pending_duplicate: '已有待审核申请', already_approved: '已批准', stale: '结果已过期', error: '提交失败' }[artifact.submission_status] || statusName[artifact.submission_status] || artifact.submission_status}{artifact.application_id ? '（申请编号 ' + artifact.application_id + '）' : ''}</p>}{identity?.role === 'user' && artifact.submission_eligible && (!artifact.submission_status || artifact.submission_status === 'error') && <button className="button-secondary" onClick={() => void submitKnowledge(artifact)} disabled={!!actionBusy}>{actionBusy === artifact.id ? '提交中…' : '申请加入知识库'}</button>}{identity?.role === 'user' && artifact.mapping_eligible && <><button className="button-secondary" onClick={() => setMappingSource({ id: artifact.id, kind: 'classification', label: '日志分类结果' })} disabled={!!actionBusy}>标准字段映射</button>{mappingForm({ id: artifact.id, kind: 'classification', label: '日志分类结果' })}</>}</article>)}</section>}
            {mappingArtifacts.length > 0 && <section className="activity-section"><h2>字段映射结果</h2>{mappingArtifacts.map(mappingSummary)}</section>}
            {conversation.session_facts_error && <p className="mapping-error" role="alert">当前业务输入不可用，历史结果仍可查看。请重新加载或上传主数据。</p>}{conversation.artifacts?.filter(item => ['enum_values', 'threat_mapping', 'config_export'].includes(item.kind) && !('result_message_id' in item && item.result_message_id && conversation.messages.some(message => message.id === item.result_message_id))).map(businessCard)}
            {identity?.role === 'user' && <details className="activity-section"><summary>枚举、威胁、填充与导出</summary><BusinessOperations key={identity.id + ':' + activeId} conversation={conversation} onDone={() => refreshActive(conversation.id)} /></details>}
            {identity?.role === 'user' && liveDrafts.length > 0 && <section className="activity-section"><h2>未应用的映射草稿</h2>{liveDrafts.map(item => <article className="result-card" key={item.id}><p>{item.changed_count} 处未应用修改{!item.base_current ? ' · 来源已过期' : ''}{item.status === 'applying' ? ' · 正在应用' : ''}</p><button className="button-secondary" onClick={() => { if (setMappingId(item.base_artifact_id)) setMappingDraftId(item.id) }}>恢复草稿</button></article>)}</section>}
            {conversation.runs.length > 0 && <section className="activity-section"><h2>执行记录</h2>{conversation.runs.map(run => <button className="run-row" key={run.id} onClick={() => {void openRun(run.id)}}><span className="run-label">{runName(run.kind || run.type)}</span><StatusText status={run.status} className="run-status" /><span className="run-detail">执行详情 ›</span></button>)}</section>}
          </div>
        </>}</div>
        {visitedTabs.includes('results') && <div className="workbench-pane" hidden={workspaceTab !== 'results'}>
          {fieldChange && !loading ? <FieldChangesWorkspace key={identity?.id + ':' + activeId + ':' + fieldChange.run_id} summary={fieldChange} editable={identity?.role === 'user'} onBack={() => { setFieldChangesId(null); changeWorkspaceTab('conversation') }} onRefresh={() => refreshActive(activeId!)} onExecution={id => {void openRun(id)}} /> : <ResultsWorkspace key={identity?.id + ':' + activeId} artifacts={conversation?.artifacts || []} active={workspaceTab === 'results'} mappingId={mappingId} mapping={mappingArtifact && !loading ? <MappingWorkspace key={identity?.id + ':' + activeId + ':' + mappingArtifact.id} artifact={mappingArtifact} onBack={() => { returnTarget.current = mappingArtifact.id; setMappingId(null); changeWorkspaceTab('conversation') }} onDownload={() => void downloadMapping(mappingArtifact.id)} downloading={downloadId === mappingArtifact.id} downloadError={downloadError?.id === mappingArtifact.id ? downloadError.message : ''} editable={identity?.role === 'user'} draftId={mappingDraftId || conversation?.drafts?.find(item => item.base_artifact_id === mappingArtifact.id && ['active', 'applying'].includes(item.status))?.id} onDraftChange={draftChanged} onPendingChange={pendingChanged} onApply={current => applyAndWait(current, viewToken.current)} onDiscard={current => discardDraft(current, viewToken.current)} /> : null} targetId={resultTarget?.id || null} targetToken={resultTarget?.token || 0} blocked={editingPending} onMapping={setMappingId} onOpen={openResult} onDownload={id => void downloadMapping(id)} />}
        </div>}
        {conversation && <>{workspaceTab === 'overview' && <div className="workbench-pane" hidden={workspaceTab !== 'overview'}><TaskOverview conversation={conversation} drafts={liveDrafts} onResults={() => changeWorkspaceTab('results')} onOpen={openResult} onTrace={() => changeWorkspaceTab('trace')} onDownload={id => void downloadMapping(id)} /></div>}{visitedTabs.includes('trace') && <div className="workbench-pane" hidden={workspaceTab !== 'trace'}><ExecutionTrace key={identity?.id + ':' + activeId} conversation={conversation} onOpen={openResult} onDetails={id => void openRun(id)} /></div>}</>}
      </div>
      <div className={"composer-region " + (workspaceTab !== "conversation" ? "is-compact" : "")}><TaskHintBar state={hintState} status={hintedRun?.status} title={hintedRun ? runName(hintedRun.kind) : ''} description={latestProgress?.runId === hintedRun?.id ? progressLabel(latestProgress?.summary) : undefined}>
        {hintedRun && <button className="button-text" onClick={() => void openRun(hintedRun.id)}>{hintState === 'failed' ? '查看失败原因' : '查看执行详情'}</button>}
        {activeRun && hintedRun?.id === activeRun.id && identity?.role === 'user' && <button className="button-text" onClick={() => void stopRun(activeRun.id)} disabled={!!actionBusy}>停止</button>}
      </TaskHintBar>
        {waitingRun && !pendingConfirmation && identity?.role === 'user' && <BusinessConfirmation key={identity.id + ':' + activeId + ':' + waitingRun.id} run={waitingRun} onBack={() => {void openRun(waitingRun.id)}} onResolved={() => refreshActive(activeId!)} />}
        {editingPending && <p className="mapping-hint composer-draft-hint" role="status">请先完成草稿保存或确认，再发送消息。</p>}<div className="composer"><textarea aria-label="消息内容" placeholder="描述要处理的日志、字段或规则…" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} rows={2} disabled={busy || clearBusy || loading || !!pendingSend || !!pendingConfirmation} /><div className="composer-toolbar"><div><label>上传用途<select aria-label="上传用途" value={uploadRole} onChange={event => setUploadRole(event.target.value as typeof uploadRole)} disabled={busy || clearBusy || loading}><option value="primary">日志或规则主数据</option><option value="enum_mapping">枚举映射附件</option></select></label><input accept={uploadRole === 'enum_mapping' ? '.xlsx' : undefined} ref={fileInput} type="file" hidden aria-label="选择文件" onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file) }} /><button className="attach-button" onClick={() => fileInput.current?.click()} disabled={busy || clearBusy || loading}>＋ 添加文件</button><span className="composer-hint">Enter 发送 · Shift+Enter 换行</span></div><button className="button-primary send-button" onClick={() => void send()} disabled={!draft.trim() || busy || clearBusy || loading || editingPending || !!pendingSend || !!pendingConfirmation}>{busy ? '处理中…' : '发送'}</button></div></div>
      </div>
    </main>
    {pendingConfirmation && <MappingDialog title="发送前处理执行方案" onClose={() => setPendingConfirmation(null)}><BusinessConfirmation key={identity?.id + ':' + activeId + ':' + pendingConfirmation.run.id + ':send'} run={pendingConfirmation.run} beforeSend onBack={() => setPendingConfirmation(null)} onResolved={async () => {const pending = pendingConfirmation; if (!isCurrent(pending.version, pending.id)) return; await refreshActive(pending.id); if (isCurrent(pending.version, pending.id)) await sendContent(pending.id, pending.content, pending.version)}} /></MappingDialog>}

    {pendingSend && <MappingDialog title="发送前处理映射草稿" onClose={returnToEditing}><p>消息尚未发送。请处理{pendingSend.drafts.length > 1 ? '当前草稿，再逐个处理其余草稿' : '未应用的修改'}。</p>{pendingSend.drafts[0] && <p>{pendingSend.drafts[0].changed_count} 处修改{!pendingSend.drafts[0].base_current ? '，来源已过期，只能丢弃或返回查看' : ''}。</p>}{resolutionError && <p role="alert" className="mapping-error">{resolutionError}</p>}<div className="mapping-actions"><button className="button-text" data-dialog-cancel onClick={returnToEditing} disabled={busy}>返回编辑</button>{pendingSend.drafts.length ? <><button className="button-text" onClick={() => void resolveSend('apply')} disabled={busy || resolutionConflict || !pendingSend.drafts[0].base_current}>应用后发送</button><button className="button-text" onClick={() => void resolveSend('discard')} disabled={busy || resolutionConflict || pendingSend.drafts[0].status === 'applying'}>丢弃后发送</button></> : <button className="button-text" onClick={() => { const pending = pendingSend; setPendingSend(null); setBusy(true); void sendContent(pending.id, pending.content, pending.version).catch(caught => { if (isCurrent(pending.version, pending.id)) setError(caught instanceof Error ? caught.message : '消息发送失败。') }).finally(() => { if (isCurrent(pending.version, pending.id)) setBusy(false) }) }}>继续发送</button>}<button className="button-text" onClick={() => void reloadResolution()} disabled={busy}>重新加载草稿状态</button></div></MappingDialog>}
    {panel && panelTabs.length > 0 && <ContextPanel key={panel.type + ':' + panel.id} panel={panel} title={selectedArtifact ? businessName(selectedArtifact.kind) + '结果' : runName(drawer?.kind)} onClose={() => setPanel(null)} tabs={panelTabs} />}
  </div>
}
