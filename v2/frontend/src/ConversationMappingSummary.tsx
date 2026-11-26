import { useEffect, useRef, useState } from 'react'
import { api, type ApiError, type FieldMappingArtifact, type MappingCandidates, type MappingConflict, type MappingDraft, type MappingDraftSummary, type MappingProposal, type MappingStatus, type MappingView, type StandardField } from './api'
import { StandardFieldPicker } from './StandardFieldPicker'
import { MappingDialog } from './MappingDialog'

const labels: Record<MappingStatus, string> = { matched: '映射成功', unmatched: '未匹配', parse_error: '解析异常' }
const summaryLimit = 8
const readableTime = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''

type ScopeDialog = { kind: 'replacement' | 'link'; operation_key: string; proposal: MappingProposal; candidates: MappingCandidates; occupied_by?: string; key: string }
type Props = { artifact: FieldMappingArtifact; draftId?: string; draftSummary?: MappingDraftSummary; editable?: boolean
  onDraftChange?: (draft: MappingDraft) => void; onPendingChange?: (pending: boolean) => void
  onOpenFull: () => void; onDownload: () => void; downloading: boolean; downloadError: string; onOpenDrawer?: () => void }

type ChangeRow = { key: string; sub_rule_id: string; source_path: string; after: string; before?: string }

export function MappingSummaryCard({ artifact, draftId, draftSummary, editable = false, onDraftChange, onPendingChange, onOpenFull, onDownload, downloading, downloadError, onOpenDrawer }: Props) {
  const [view, setView] = useState<MappingView | null>(null)
  const [viewError, setViewError] = useState('')
  const [viewRetry, setViewRetry] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const [changesOpen, setChangesOpen] = useState(false)
  const [changesExpanded, setChangesExpanded] = useState(false)
  const [editing, setEditing] = useState(false)
  const [mappingDraft, setMappingDraft] = useState<MappingDraft | null>(null)
  const [beforeValues, setBeforeValues] = useState<Record<string, string>>({})
  const [beforeError, setBeforeError] = useState('')
  const [catalog, setCatalog] = useState<StandardField[]>([])
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState('')
  const [revisionConflict, setRevisionConflict] = useState(false)
  const [pendingEdit, setPendingEdit] = useState<{ operation_key: string; proposal: MappingProposal } | null>(null)
  const [scope, setScope] = useState<ScopeDialog | null>(null)
  const [reload, setReload] = useState(0)
  const live = useRef(0)
  const callbacks = useRef({ onDraftChange, onPendingChange })
  callbacks.current = { onDraftChange, onPendingChange }
  const artifactId = artifact.id
  const draftIdentity = mappingDraft?.id, draftRevision = mappingDraft?.revision, baseCurrent = mappingDraft?.base_current
  useEffect(() => { const epoch = live; ++epoch.current; return () => { ++epoch.current; callbacks.current.onPendingChange?.(false) } }, [artifactId])
  const updateDraft = (next: MappingDraft) => { setMappingDraft(next); callbacks.current.onDraftChange?.(next) }
  const pending = (value: boolean) => callbacks.current.onPendingChange?.(value)
  // 完整草稿按需加载：仅在用户展开修改明细或进入行内调整时读取/创建，
  // 普通查看只消费会话响应中的草稿摘要，不产生额外写请求。
  const loadedDraft = useRef<{ id: string; artifact: string; reload: number } | null>(null)
  useEffect(() => {
    if (!editing && !changesOpen) return
    const current = loadedDraft.current
    if (current && current.artifact === artifactId && current.reload === reload && (!draftId || current.id === draftId)) return
    let active = true
    setEditError(''); setRevisionConflict(false)
    const load = draftId ? api.mappingDraft(draftId) : api.createMappingDraft(artifactId)
    load.then(next => {
      if (!active) return
      loadedDraft.current = { id: next.id, artifact: artifactId, reload }
      updateDraft(next); setPendingEdit(null); setScope(null); pending(false)
    }).catch(caught => { if (active) setEditError(caught instanceof Error ? caught.message : '草稿加载失败，请重试。') })
    return () => { active = false }
  }, [artifactId, draftId, editing, changesOpen, reload])
  useEffect(() => {
    // #465 三层分工：填充卡自足承载操作，不再加载映射编辑表格。
    if (artifact.operation) return
    const controller = new AbortController()
    let active = true
    setViewError('')
    api.mappingView(artifactId, { page: 1, q: '', status: '', ...(draftIdentity ? { draft_id: draftIdentity } : {}) }, controller.signal).then(result => {
      if (active) setView(result)
    }).catch(caught => { if (active) setViewError(caught instanceof Error ? caught.message : '结果加载失败，请重试。') })
    return () => { active = false; controller.abort() }
  }, [artifactId, viewRetry, draftIdentity, draftRevision, artifact.operation])
  const changeRows: ChangeRow[] = (mappingDraft?.operations || []).flatMap(operation => operation.changes.map(change => ({
    key: operation.operation_key + ':' + change.sub_rule_id + ':' + change.source_path,
    sub_rule_id: change.sub_rule_id, source_path: change.source_path, after: change.standard_field || '',
    before: beforeValues[JSON.stringify([change.sub_rule_id, change.source_path])]
  })))
  useEffect(() => {
    if (!changesOpen || !mappingDraft) return
    if (!mappingDraft.operations.length) { setBeforeValues({}); setBeforeError(''); return }
    const controller = new AbortController()
    let active = true
    setBeforeError('')
    const changes = mappingDraft.operations.flatMap(operation => operation.changes)
    Promise.all(changes.map(async change => {
      const result = await api.mappingView(artifactId, { sub_rule: change.sub_rule_id, page: 1, q: change.source_path, status: '' }, controller.signal)
      const row = result.items.find(item => item.source_path === change.source_path)
      return [JSON.stringify([change.sub_rule_id, change.source_path]), row?.standard_field ?? ''] as const
    })).then(entries => { if (active) setBeforeValues(Object.fromEntries(entries)) })
      .catch(() => { if (active) setBeforeError('部分修改前取值未能确认，对应单元格显示为“—”。') })
    return () => { active = false; controller.abort() }
  }, [artifactId, changesOpen, mappingDraft])
  useEffect(() => {
    if (!draftIdentity || view?.sub_rule_id === undefined || !editing || !baseCurrent) return
    const controller = new AbortController()
    let active = true
    api.standardFields(draftIdentity, view.sub_rule_id, controller.signal).then(result => { if (active) setCatalog(result.items) }).catch(() => {})
    return () => { active = false; controller.abort() }
  }, [draftIdentity, draftRevision, baseCurrent, view?.sub_rule_id, editing])
  const handleEditError = (caught: unknown) => {
    const recovered = (caught as { mappingDraft?: MappingDraft })?.mappingDraft
    if (recovered) updateDraft(recovered)
    setEditError(caught instanceof Error ? caught.message : '草稿保存失败，选择已保留，请重试。')
    if ((caught as ApiError)?.code === 'draft_revision_conflict') setRevisionConflict(true)
  }
  const writesBlocked = saving || !!pendingEdit || !!scope || revisionConflict || !baseCurrent || mappingDraft?.status !== 'active'
  const save = async (operation_key: string, proposal: MappingProposal, showCandidates = true) => {
    if (!mappingDraft || saving || revisionConflict) return
    const version = live.current
    setSaving(true); setEditError(''); setPendingEdit({ operation_key, proposal }); pending(true)
    try {
      const result = await api.saveMapping(mappingDraft.id, mappingDraft.revision, operation_key, proposal)
      if (version !== live.current) return
      updateDraft(result.draft); setPendingEdit(null)
      if (showCandidates && result.candidates.items.length) setScope({ kind: 'link', operation_key, proposal, candidates: result.candidates, key: crypto.randomUUID() })
      else { setScope(null); pending(false) }
    } catch (caught) {
      if (version !== live.current) return
      if ((caught as ApiError).code === 'mapping_target_conflict' && (caught as ApiError).details) {
        const conflict = (caught as ApiError).details as MappingConflict
        setScope({ kind: 'replacement', ...conflict, key: crypto.randomUUID() }); setEditError('')
      } else handleEditError(caught)
    } finally { if (version === live.current) setSaving(false) }
  }
  const cancelScope = () => {
    if (saving) return
    setScope(null); setPendingEdit(null); pending(false)
  }
  const confirmScope = async () => {
    if (!scope || !mappingDraft || saving || revisionConflict) return
    if (scope.kind === 'link') { void save(scope.operation_key, scope.proposal, false); return }
    const version = live.current
    setSaving(true); setEditError('')
    try {
      const result = await api.confirmMapping(mappingDraft.id, mappingDraft.revision, scope as MappingConflict, scope.proposal, true, scope.key)
      if (version !== live.current) return
      updateDraft(result.draft); setPendingEdit(null); setScope(null); pending(false)
    } catch (caught) { if (version === live.current) handleEditError(caught) }
    finally { if (version === live.current) setSaving(false) }
  }
  const draftStateSource = mappingDraft && (editing || changesOpen) ? mappingDraft : draftSummary
  const draftStateText = !draftStateSource ? '' : draftStateSource.status === 'applying' ? '修改正在应用，可查看执行进度。' : draftStateSource.status === 'applied' ? '修改已应用为新版本。' : draftStateSource.changed_count ? `${draftStateSource.changed_count} 处修改已保存为草稿，尚未应用。` : '草稿与正式结果一致，没有待应用的修改。'
  const rows = view ? (expanded ? view.items : view.items.slice(0, summaryLimit)) : []
  const changeView = changesExpanded ? changeRows : changeRows.slice(0, summaryLimit)
  // #461：卡片标题与摘要跟随输入意图——填充产物（operation 元数据）不再冒充「标准字段映射」。
  const fillTitle = artifact.operation === 'enum_fill' ? '枚举值填充完成' : artifact.operation === 'threat_fill' ? '威胁类型填充完成' : null
  // #465 三层分工：填充卡自足承载操作——无映射表格、无行内编辑、无草稿区、无后续处理入口，
  // 只留标题 + 目标字段摘要 + 下载配置 / 在结果工作区打开。
  if (fillTitle) return <article className="result-card mapping-summary-card" id={'mapping-' + artifact.id}>
    <div className="result-heading"><strong>{fillTitle}</strong><span>{readableTime(artifact.created_at)}</span></div>
    <p>{artifact.target_fields?.length ? <>目标字段 {artifact.target_fields.join('、')} · </> : null}填充已写入当前配置。</p>
    {!artifact.current && <p className="mapping-warning">结果已过期，可查看和下载历史配置。</p>}
    <div className="mapping-actions"><button className="button-secondary" onClick={onDownload} disabled={downloading}>{downloading ? '下载中…' : '下载配置'}</button>{onOpenDrawer && <button className="button-secondary" onClick={onOpenDrawer}>在结果工作区打开</button>}</div>
    {downloadError && <p className="mapping-error" role="alert">{downloadError}</p>}
  </article>
  return <article className="result-card mapping-summary-card" id={'mapping-' + artifact.id}>
    <div className="result-heading"><strong>标准字段映射完成</strong><span>{readableTime(artifact.created_at)}</span></div>
    <p>{artifact.summary.rule_count} 条子规则，{artifact.summary.field_count} 个字段 · 映射成功 {artifact.summary.matched_count} · 未匹配 {artifact.summary.unmatched_count} · 解析异常 {artifact.summary.parse_error_count}</p>
    {(artifact.summary.uncertain_annotation_count || 0) > 0 && <p className="mapping-warning">待人工确认：{artifact.summary.uncertain_annotation_count} 条事件名称标注。</p>}
    {artifact.summary.warning_codes?.includes('threat_chain_warning') && <p className="mapping-warning">威胁类型处理有提醒，请查看结果。</p>}
    {!artifact.current && <p className="mapping-warning">结果已过期，可查看和下载历史配置。</p>}
    {viewError && <div className="mapping-error" role="alert"><span>{viewError}</span><button className="button-secondary" onClick={() => setViewRetry(viewRetry + 1)}>重试加载</button></div>}
    {view && <div className="summary-table-region"><table className="mapping-table summary-table"><caption className="sr-only">字段映射摘要（当前子规则）</caption><thead><tr><th scope="col">原始字段</th><th scope="col">标准字段</th><th scope="col">状态</th></tr></thead><tbody>{rows.map(row => <tr key={row.operation_key || row.source_path} data-source={row.source_path}><td><span className="mapping-source mono" title={row.source_path}>{row.source_path}</span></td><td>{editable && editing && mappingDraft && row.operation_key ? <><StandardFieldPicker label={row.source_path + ' 标准字段'} source={row.source_path} value={pendingEdit?.operation_key === row.operation_key ? pendingEdit.proposal.standard_field || '' : row.standard_field || ''} fields={catalog} disabled={writesBlocked || row.editable === false || !catalog.length} onSelect={value => void save(row.operation_key!, { sub_rule_id: row.sub_rule_id || view.sub_rule_id, source_path: row.source_path, standard_field: value || null, linked_sub_rule_ids: [] })} />{row.disabled_reason && <small className="mapping-hint">{row.disabled_reason === 'mapping_source_not_editable' ? '该字段由平台维护，不能在此修改。' : '该字段不能在此修改。'}</small>}{row.draft_modified && <small className="mapping-draft-mark">草稿已修改</small>}</> : <span className="mapping-value" title={row.standard_field}>{row.standard_field || '未映射'}</span>}</td><td><span className={'mapping-badge mapping-' + row.status}>{labels[row.status]}</span></td></tr>)}</tbody></table>{view.items.length > summaryLimit && <button className="button-text summary-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '收起摘要行' : '展开全部 ' + view.items.length + ' 行'}</button>}{view.total > view.items.length && <p className="mapping-hint">当前子规则共 {view.total} 个字段，摘要仅显示首页 {view.page_size} 行。</p>}</div>}
    {(draftSummary || draftId) && <section className="summary-changes" aria-label="草稿修改状态">
      <h3>{draftStateSource?.changed_count ? '未应用修改' : '草稿修改'}</h3>
      <p role="status" className="mapping-hint">{draftStateText}{draftStateSource && !draftStateSource.base_current && ' 草稿来源已过期，只能查看或丢弃。'}</p>
      <button className="button-text summary-toggle" aria-expanded={changesOpen} onClick={() => setChangesOpen(!changesOpen)}>{changesOpen ? '收起修改明细' : '展开修改明细'}</button>
      {changesOpen && (mappingDraft ? (changeRows.length > 0 ? <div className="summary-table-region"><table className="mapping-table summary-table"><caption className="sr-only">草稿修改明细</caption><thead><tr><th scope="col">原始字段</th><th scope="col">修改前</th><th scope="col">修改后</th></tr></thead><tbody>{changeView.map(row => <tr key={row.key}><td><span className="mapping-source mono" title={row.source_path}>{row.source_path}</span></td><td>{row.before === undefined ? (beforeError ? '—' : '读取中…') : row.before || '未映射'}</td><td>{row.after || '未映射'}</td></tr>)}</tbody></table>{beforeError && <p className="mapping-warning" role="status">{beforeError}</p>}{changeRows.length > summaryLimit && <button className="button-text summary-toggle" aria-expanded={changesExpanded} onClick={() => setChangesExpanded(!changesExpanded)}>{changesExpanded ? '收起修改行' : '展开全部 ' + changeRows.length + ' 处修改'}</button>}</div> : <p className="mapping-hint">这份草稿没有待应用的字段修改。</p>) : <p role="status">正在读取修改明细…</p>)}
    </section>}
    {editError && <div className="mapping-error" role="alert"><span>{editError}</span>{pendingEdit && !revisionConflict && <button className="button-secondary" onClick={() => void save(pendingEdit.operation_key, pendingEdit.proposal)} disabled={saving}>重试保存</button>}{mappingDraft && <button className="button-secondary" onClick={() => setReload(reload + 1)} disabled={saving}>重新加载草稿{pendingEdit ? '（放弃未保存选择）' : ''}</button>}</div>}
    {downloadError && <p className="mapping-error" role="alert">{downloadError}</p>}
    <div className="mapping-actions"><button className="button-secondary" onClick={onOpenFull} disabled={saving || !!pendingEdit || !!scope}>查看完整结果</button>{onOpenDrawer && <button className="button-secondary" onClick={onOpenDrawer} disabled={saving || !!pendingEdit || !!scope}>后续处理</button>}{editable && artifact.current && !editing && <button className="button-secondary" onClick={() => setEditing(true)} disabled={saving || !!pendingEdit || !!scope}>行内调整</button>}{editing && <button className="button-secondary" onClick={() => { setEditing(false); setCatalog([]) }} disabled={saving || !!pendingEdit || !!scope}>结束调整</button>}<button className="button-secondary" onClick={onDownload} disabled={downloading || saving || !!pendingEdit || !!scope}>{downloading ? '下载中…' : '下载配置'}</button></div>
    {scope && <MappingDialog title={scope.kind === 'replacement' ? '确认替换映射' : '是否联动相同字段'} onClose={cancelScope}>
      {scope.kind === 'replacement' ? <p>标准字段“{scope.proposal.standard_field}”已被“{scope.occupied_by}”占用。确认后取消原占用者的映射，并改为“{scope.proposal.source_path}”。</p> : <p>当前子规则已自动保存。可选择其他完整路径相同的字段一并修改；默认只保留当前子规则。</p>}
      <p className="mono">{scope.proposal.source_path}</p><div className="mapping-link-list">{scope.candidates.items.map(item => <label key={item.sub_rule_id}><input type="checkbox" aria-label={'联动 ' + item.name} disabled={saving || !item.selectable || revisionConflict} checked={scope.proposal.linked_sub_rule_ids.includes(item.sub_rule_id)} onChange={event => setScope({ ...scope, key: crypto.randomUUID(), proposal: { ...scope.proposal, linked_sub_rule_ids: event.target.checked ? [...scope.proposal.linked_sub_rule_ids, item.sub_rule_id] : scope.proposal.linked_sub_rule_ids.filter(id => id !== item.sub_rule_id) } })} /><span>{item.name}<small>当前：{item.current_standard_field || '未映射'} · 样例：{item.samples.join('、') || '无非空样例'}</small>{!item.selectable && <small className="mapping-warning">{item.disabled_reason === 'mapping_source_not_editable' || !item.conflict_source_path ? '该字段不能修改，不能联动。' : '目标已被 ' + item.conflict_source_path + ' 占用，不能联动。'}</small>}</span></label>)}</div>
      {editError && <p className="mapping-error" role="alert">{editError}</p>}
      <div className="mapping-actions"><button className="button-text" data-dialog-cancel onClick={cancelScope} disabled={saving}>{scope.kind === 'replacement' ? '取消替换' : '仅保留当前子规则'}</button><button className="button-text" onClick={() => void confirmScope()} disabled={saving || revisionConflict}>{scope.kind === 'replacement' ? '确认替换并保存' : '保存所选联动'}</button></div>
    </MappingDialog>}
  </article>
}
