import { useEffect, useRef, useState } from 'react'
import { api, type FieldMappingArtifact, type MappingQuery, type MappingStatus, type MappingView, type MappingDraft, type MappingProposal, type MappingCandidates, type MappingConflict, type StandardField, type ApiError } from './api'

import { StandardFieldPicker } from './StandardFieldPicker'
import { MappingDialog } from './MappingDialog'

const labels: Record<MappingStatus, string> = { matched: '映射成功', unmatched: '未匹配', parse_error: '解析异常' }
const statuses: MappingStatus[] = ['matched', 'unmatched', 'parse_error']
type Props = { artifact: FieldMappingArtifact; onBack: () => void; onDownload: () => void; downloading: boolean; downloadError: string
  editable?: boolean; draftId?: string; onDraftChange?: (draft: MappingDraft) => void; onPendingChange?: (pending: boolean) => void
  onApply?: (draft: MappingDraft) => Promise<MappingDraft | null>; onDiscard?: (draft: MappingDraft) => Promise<MappingDraft | null> }
type ScopeDialog = { kind: 'replacement' | 'link'; operation_key: string; proposal: MappingProposal; candidates: MappingCandidates; occupied_by?: string; key: string }


export function MappingWorkspace({ artifact, onBack, onDownload, downloading, downloadError, editable = false, draftId, onDraftChange, onPendingChange, onApply, onDiscard }: Props) {
  const [query, setServerQuery] = useState<MappingQuery>({ page: 1, q: '', status: '' })
  const [retained, setRetained] = useState<{ scope: string; view: MappingView } | null>(null)
  const setQuery = (next: MappingQuery) => { setRetained(null); setServerQuery(next) }
  const [search, setSearch] = useState('')
  const [result, setResult] = useState<{ id: string; revision: number | undefined; view: MappingView } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [mappingDraft, setMappingDraft] = useState<MappingDraft | null>(null)
  const [catalog, setCatalog] = useState<StandardField[]>([])
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState('')
  const [revisionConflict, setRevisionConflict] = useState(false)
  const [reload, setReload] = useState(0)
  const [pendingEdit, setPendingEdit] = useState<{ operation_key: string; proposal: MappingProposal } | null>(null)
  const [scope, setScope] = useState<ScopeDialog | null>(null)
  const [draftNotice, setDraftNotice] = useState('')
  const live = useRef(0)
  const loadedDraft = useRef<{ id: string; artifact: string; reload: number } | null>(null)
  const callbacks = useRef({ onDraftChange, onPendingChange, onApply, onBack })
  callbacks.current = { onDraftChange, onPendingChange, onApply, onBack }
  const artifactId = artifact.id, artifactCurrent = artifact.current
  const draftIdentity = mappingDraft?.id, draftRevision = mappingDraft?.revision, baseCurrent = mappingDraft?.base_current
  useEffect(() => { const epoch = live; ++epoch.current; return () => { ++epoch.current; callbacks.current.onPendingChange?.(false) } }, [artifactId])
  const updateDraft = (next: MappingDraft) => { setMappingDraft(next); callbacks.current.onDraftChange?.(next) }
  const pending = (value: boolean) => callbacks.current.onPendingChange?.(value)
  useEffect(() => {
    if (!editable || (!artifactCurrent && !draftId)) return
    if (draftId && loadedDraft.current?.id === draftId && loadedDraft.current.artifact === artifactId && loadedDraft.current.reload === reload) return
    let active = true
    setEditError(''); setRevisionConflict(false)
    const load = draftId ? api.mappingDraft(draftId) : api.createMappingDraft(artifactId)
    load.then(next => {
      if (!active) return
      loadedDraft.current = { id: next.id, artifact: artifactId, reload }
      setMappingDraft(next); callbacks.current.onDraftChange?.(next)
      setPendingEdit(null); setScope(null); callbacks.current.onPendingChange?.(false)
      setDraftNotice(next.changed_count ? '已恢复自动保存的草稿。' : '选择标准字段后自动保存草稿。')

    }).catch(caught => { if (active) setEditError(caught instanceof Error ? caught.message : '草稿加载失败，请重试。') })
    return () => { active = false }
  }, [artifactId, artifactCurrent, editable, draftId, reload])
  const handleEditError = (caught: unknown) => {
    const recovered = (caught as { mappingDraft?: MappingDraft })?.mappingDraft
    if (recovered) updateDraft(recovered)
    setEditError(caught instanceof Error ? caught.message : '草稿保存失败，选择已保留，请重试。')
    if ((caught as ApiError)?.code === 'draft_revision_conflict') setRevisionConflict(true)
  }
  const failureHandler = useRef(handleEditError)
  failureHandler.current = handleEditError
  const restoredDraft = useRef(mappingDraft)
  restoredDraft.current = mappingDraft
  const restoringApply = mappingDraft?.status === 'applying'
  useEffect(() => {
    if (!restoringApply || !draftIdentity || !callbacks.current.onApply) return
    let active = true
    const current = restoredDraft.current!
    setSaving(true); callbacks.current.onPendingChange?.(true)
    void callbacks.current.onApply(current).then(applied => {
      if (!active) return
      setSaving(false); callbacks.current.onPendingChange?.(false)
      if (!applied) return
      setMappingDraft(applied); callbacks.current.onDraftChange?.(applied)
      if (applied.status === 'applied') callbacks.current.onBack()
    }).catch(caught => { if (active) { setSaving(false); callbacks.current.onPendingChange?.(false); failureHandler.current(caught) } })
    return () => { active = false }
  }, [restoringApply, draftIdentity])
  const serverData = result?.id === artifact.id ? result.view : null
  const changes = new Map(mappingDraft?.operations.flatMap(operation => operation.changes).map(change => [JSON.stringify([change.sub_rule_id, change.source_path]), change]) || [])
  const data = serverData && retained?.scope === JSON.stringify(query) ? { ...serverData, total: retained.view.total, items: retained.view.items.map(row => {
    const updated = serverData.items.find(item => item.source_path === row.source_path)
    if (updated && result?.revision === draftRevision) return updated
    const change = changes.get(JSON.stringify([row.sub_rule_id || serverData.sub_rule_id, row.source_path]))
    return change ? { ...(updated || row), standard_field: change.standard_field || '', draft_modified: true, user_modified: true, evidence: updated?.evidence || '用户调整的草稿映射', status: row.status === 'parse_error' ? row.status : change.standard_field ? 'matched' as const : 'unmatched' as const, group_status: row.group_status || row.status } : updated || row
  }) } : serverData
  useEffect(() => {
    const controller = new AbortController()
    let live = true
    setLoading(true); setError('')
    api.mappingView(artifactId, { ...query, ...(draftIdentity ? { draft_id: draftIdentity } : {}) }, controller.signal).then(view => {
      if (live) setResult({ id: artifactId, revision: draftRevision, view })
    }).catch(caught => {
      if (live) setError(caught instanceof Error ? caught.message : '结果加载失败，请重试。')
    }).finally(() => { if (live) setLoading(false) })
    return () => { live = false; controller.abort() }
  }, [artifactId, query, retry, draftIdentity, draftRevision])
  const visibleRule = data?.sub_rule_id
  useEffect(() => {
    if (!draftIdentity || visibleRule === undefined || !editable || !baseCurrent) return
    const controller = new AbortController()
    let active = true
    setCatalog([])
    api.standardFields(draftIdentity, visibleRule, controller.signal).then(result => { if (active) setCatalog(result.items) }).catch(caught => { if (active) setEditError(caught instanceof Error ? caught.message : '标准字段加载失败。') })
    return () => { active = false; controller.abort() }
  }, [draftIdentity, draftRevision, baseCurrent, visibleRule, editable])
  const writesBlocked = loading || !!error || saving || !!pendingEdit || !!scope || revisionConflict || !mappingDraft?.base_current || mappingDraft.status !== 'active'
  const save = async (operation_key: string, proposal: MappingProposal, showCandidates = true) => {
    if (!mappingDraft || saving || revisionConflict) return
    const version = live.current
    if (data) setRetained(current => current || { scope: JSON.stringify(query), view: data })
    setSaving(true); setEditError(''); setPendingEdit({ operation_key, proposal }); pending(true)
    try {
      const result = await api.saveMapping(mappingDraft.id, mappingDraft.revision, operation_key, proposal)
      if (version !== live.current) return
      updateDraft(result.draft); setPendingEdit(null); setDraftNotice('草稿已自动保存。')
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
    setDraftNotice(scope?.kind === 'link' ? '已保留当前子规则的修改，未新增联动。' : '已取消替换，草稿没有变化。')
  }
  const confirmScope = async () => {
    if (!scope || !mappingDraft || saving || revisionConflict) return
    if (scope.kind === 'link') { await save(scope.operation_key, scope.proposal, false); return }
    const version = live.current
    setSaving(true); setEditError('')
    try {
      const result = await api.confirmMapping(mappingDraft.id, mappingDraft.revision, scope as MappingConflict, scope.proposal, true, scope.key)
      if (version !== live.current) return
      updateDraft(result.draft); setPendingEdit(null); setScope(null); pending(false); setDraftNotice('替换和所选联动已自动保存。')
    } catch (caught) { if (version === live.current) handleEditError(caught) }
    finally { if (version === live.current) setSaving(false) }
  }
  const draftAction = async (action: 'apply' | 'discard') => {
    if (!mappingDraft || saving) return
    const version = live.current
    setSaving(true); pending(true); setEditError('')
    try {
      const next = await (action === 'apply' ? onApply?.(mappingDraft) : onDiscard?.(mappingDraft))
      if (version !== live.current || !next) return
      updateDraft(next); setPendingEdit(null); setScope(null); pending(false)
      if (next.status === 'applied' || next.status === 'discarded') onBack()
    } catch (caught) { if (version === live.current) handleEditError(caught) }
    finally { if (version === live.current) { setSaving(false); if (!pendingEdit && !scope) pending(false) } }
  }

  const selectRule = (id: string) => setQuery({ ...query, sub_rule: id, page: 1 })
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  return <section className="mapping-workspace" aria-label="字段映射结果">
    <header className="mapping-header"><div><h2>字段映射结果</h2><p>{artifact.summary.rule_count} 条子规则，{artifact.summary.field_count} 个字段</p></div><div className="mapping-actions"><button className="button-secondary" onClick={onBack} disabled={saving || !!pendingEdit || !!scope}>返回对话</button><button className="button-secondary" onClick={onDownload} disabled={downloading}>{downloading ? '下载中…' : '下载配置'}</button></div></header>
    {!artifact.current && <p className="mapping-warning" role="status">结果已过期，保留用于查看和下载。请从当前输入重新执行映射。</p>}
    {editable && <section className="mapping-draft-state" aria-label="映射草稿"><div><strong>{saving ? '正在保存或应用…' : mappingDraft?.status === 'applying' ? '修改正在应用' : mappingDraft?.changed_count ? '未应用的草稿' : '映射草稿'}</strong><p role="status">{draftNotice}</p>{mappingDraft && <p>{mappingDraft.changed_count} 处修改 · 自动保存后仍需应用</p>}{mappingDraft && !mappingDraft.base_current && <p className="mapping-warning">草稿来源已过期，只能查看或丢弃。</p>}</div><div className="mapping-actions">{mappingDraft && onApply && <button className="button-primary" onClick={() => void draftAction('apply')} disabled={saving || !!pendingEdit || !!scope || revisionConflict || !mappingDraft.base_current || !mappingDraft.changed_count || !['active', 'applying'].includes(mappingDraft.status)}>{mappingDraft.status === 'applying' ? '查询应用结果' : '应用修改并继续'}</button>}{mappingDraft && onDiscard && <button className="button-secondary" onClick={() => void draftAction('discard')} disabled={saving || mappingDraft.status === 'applying'}>丢弃草稿</button>}</div></section>}
    {editError && <div className="mapping-error" role="alert"><span>{editError}</span>{pendingEdit && !revisionConflict && <button className="button-secondary" onClick={() => void save(pendingEdit.operation_key, pendingEdit.proposal)} disabled={saving}>重试保存</button>}<button className="button-secondary" onClick={() => setReload(reload + 1)} disabled={saving}>重新加载草稿{pendingEdit ? '（放弃未保存选择）' : ''}</button></div>}
    {downloadError && <p className="mapping-error" role="alert">{downloadError}</p>}
    {data && <>
      {!!data.warnings?.length && <section className="mapping-business-warnings" aria-label="威胁类型处理提醒"><h3>威胁类型处理提醒</h3><ul>{data.warnings.map((warning, index) => <li key={warning.code + index}>{warning.message}</li>)}</ul></section>}
      <details className="mapping-annotations" aria-label="事件名称标注明细"><summary>事件名称标注 · {data.event_annotations?.length || 0} 条</summary>{data.event_annotations?.length ? <div className="mapping-table-region annotation-table-region"><table className="annotation-table" aria-label="事件名称标注"><colgroup><col /><col /><col /><col /><col /><col /></colgroup><thead><tr><th scope="col">子规则</th><th scope="col">事件名称</th><th scope="col">事件级别</th><th scope="col">威胁判定来源（仅威胁事件）</th><th scope="col">威胁判定结果（仅威胁事件）</th><th scope="col">状态</th></tr></thead><tbody>{data.event_annotations.map((annotation, index) => {
        const operational = annotation.status === 'judged' && (annotation.threat_source_field === '不适用' || annotation.event_level === '信息')
        return <tr key={annotation.rule_name + index}>
          <td>{annotation.rule_name || '未命名子规则'}</td>
          <td>{annotation.event_name || '未生成'}{operational && <small>操作/审计事件</small>}</td>
          <td>{!annotation.event_level || annotation.event_level === 'unknown' ? '未知' : annotation.event_level}</td>
          <td className="mono">{operational ? '不适用' : annotation.threat_source_field || '未确定'}</td>
          <td>{operational ? '不适用' : annotation.threat_types.length ? annotation.threat_types.join('、') : '未生成'}</td>
          <td><span className={'mapping-badge ' + (annotation.status === 'judged' ? 'mapping-matched' : 'mapping-unmatched')}>{annotation.status === 'judged' ? '已判定' : '待人工确认'}</span></td>
        </tr>
      })}</tbody></table></div> : <p className="mapping-hint">未生成事件名称标注。</p>}</details>
      <div className="mapping-rule-navigation"><div className="mapping-tabs" role="tablist" aria-label="子规则">{data.sub_rules.map(rule => <button role="tab" aria-selected={data.sub_rule_id === rule.id} className="mapping-tab" disabled={saving || !!pendingEdit || !!scope} key={rule.id} onClick={() => selectRule(rule.id)} title={rule.name}>{rule.name}<small>{rule.field_count}</small></button>)}</div><label>全部子规则<select aria-label="全部子规则" disabled={saving || !!pendingEdit || !!scope} value={data.sub_rule_id} onChange={event => selectRule(event.target.value)}>{data.sub_rules.map(rule => <option value={rule.id} key={rule.id}>{rule.name}</option>)}</select></label></div>
      <div className="mapping-toolbar"><form onSubmit={event => { event.preventDefault(); setQuery({ ...query, sub_rule: data.sub_rule_id, q: search.trim(), page: 1 }) }}><input type="search" disabled={saving || !!pendingEdit || !!scope} aria-label="搜索字段或样例" placeholder="搜索字段或样例" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} /><button className="button-secondary" type="submit" disabled={saving || !!pendingEdit || !!scope}>搜索</button></form><label>状态筛选<select aria-label="状态筛选" disabled={saving || !!pendingEdit || !!scope} value={query.status} onChange={event => setQuery({ ...query, sub_rule: data.sub_rule_id, status: event.target.value, page: 1 })}><option value="">全部状态</option>{statuses.map(status => <option key={status} value={status}>{labels[status]}</option>)}</select></label></div>
      <p className="mapping-hint">搜索和筛选覆盖当前子规则的全部字段。样例位置表示原始日志条目序号。</p>{retained && <p className="mapping-hint" role="status">本轮编辑的行暂留在当前筛选结果。<button className="button-text" disabled={saving || !!pendingEdit || !!scope} onClick={() => { setRetained(null); setRetry(retry + 1) }}>刷新筛选结果</button></p>}
    </>}
    {loading && <p className="mapping-loading" role="status"><span className="loading-spinner" />正在加载字段…</p>}
    {error && <div className="mapping-error" role="alert"><span>{error}</span><button className="button-secondary" onClick={() => setRetry(retry + 1)}>重试加载</button></div>}
    {data && error && <p className="mapping-hint">以下保留上次成功加载的结果。</p>}
    {data && <div className="mapping-table-region" aria-busy={loading}><table className="mapping-table"><caption className="sr-only">当前子规则的字段映射</caption><thead><tr><th scope="col">原始字段</th><th scope="col">数据样例</th><th scope="col">映射的标准字段</th><th scope="col">匹配依据</th><th scope="col">状态</th>{editable && <th scope="col">操作</th>}</tr></thead>{statuses.map(status => {
      const rows = data.items.filter(row => (row.group_status || row.status) === status)
      return rows.length ? <tbody key={status}><tr className="mapping-group"><th colSpan={editable ? 6 : 5} scope="rowgroup">{labels[status]}</th></tr>{rows.map(row => <tr key={row.operation_key || row.source_path} data-source={row.source_path}><td><span className="mapping-source mono" title={row.source_path}>{row.source_path}</span></td><td>{row.samples.length ? <><ul className="mapping-samples">{row.samples.slice(0, 3).map((value, index) => <li key={index} title={value}>{value}</li>)}</ul>{row.expanded_samples.length > 0 && <details className="mapping-more"><summary>查看更多样例</summary><ol>{row.expanded_samples.slice(0, 20).map((sample, index) => <li key={index}><span className="mono">{sample.value}</span><small>{sample.line_number != null ? '日志条目 ' + sample.line_number : '配置样例（无日志位置）'}</small></li>)}</ol></details>}</> : <span className="mapping-hint">无非空样例</span>}</td><td>{editable && mappingDraft && row.operation_key ? <><StandardFieldPicker label={row.source_path + ' 标准字段'} source={row.source_path} value={pendingEdit?.operation_key === row.operation_key ? pendingEdit.proposal.standard_field || '' : row.standard_field || ''} fields={catalog} disabled={writesBlocked || row.editable === false || !catalog.length} onSelect={value => void save(row.operation_key!, { sub_rule_id: row.sub_rule_id || data.sub_rule_id, source_path: row.source_path, standard_field: value || null, linked_sub_rule_ids: [] })} />{row.disabled_reason && <small className="mapping-hint">{row.disabled_reason === 'mapping_source_not_editable' ? '该字段由平台维护，不能在此修改。' : '该字段不能在此修改。'}</small>}{row.draft_modified && <small className="mapping-draft-mark">草稿已修改</small>}</> : <span className="mapping-value" title={row.standard_field}>{row.standard_field || '未映射'}</span>}</td><td><span className="mapping-evidence" title={row.evidence}>{row.evidence || '无匹配依据'}</span>{row.warning && <small className="mapping-warning">{row.warning}</small>}</td><td><span className={'mapping-badge mapping-' + row.status}>{labels[row.status]}</span></td>{editable && <td><button className="button-secondary" aria-label={row.source_path + ' 取消映射'} disabled={writesBlocked || row.editable === false || !row.standard_field || !row.operation_key} onClick={() => void save(row.operation_key!, { sub_rule_id: row.sub_rule_id || data.sub_rule_id, source_path: row.source_path, standard_field: null, linked_sub_rule_ids: [] })}>取消映射</button></td>}</tr>)}</tbody> : null
    })}</table>{data.items.length === 0 && !loading && <p className="mapping-empty">没有符合条件的字段。</p>}</div>}
    {data && <footer className="mapping-pagination"><span>共 {data.total} 个字段 · 每页 {data.page_size} 个</span><div><button className="button-secondary" disabled={saving || !!pendingEdit || !!scope || loading || data.page <= 1} onClick={() => setQuery({ ...query, sub_rule: data.sub_rule_id, page: data.page - 1 })}>上一页</button><span>第 {data.page} / {pages} 页</span><button className="button-secondary" disabled={saving || !!pendingEdit || !!scope || loading || data.page >= pages} onClick={() => setQuery({ ...query, sub_rule: data.sub_rule_id, page: data.page + 1 })}>下一页</button></div></footer>}
    {scope && <MappingDialog title={scope.kind === 'replacement' ? '确认替换映射' : '是否联动相同字段'} onClose={cancelScope}>
      {scope.kind === 'replacement' ? <p>标准字段“{scope.proposal.standard_field}”已被“{scope.occupied_by}”占用。确认后取消原占用者的映射，并改为“{scope.proposal.source_path}”。</p> : <p>当前子规则已自动保存。可选择其他完整路径相同的字段一并修改；默认只保留当前子规则。</p>}
      <p className="mono">{scope.proposal.source_path}</p><div className="mapping-link-list">{scope.candidates.items.map(item => <label key={item.sub_rule_id}><input type="checkbox" aria-label={'联动 ' + item.name} disabled={saving || !item.selectable || revisionConflict} checked={scope.proposal.linked_sub_rule_ids.includes(item.sub_rule_id)} onChange={event => setScope({ ...scope, key: crypto.randomUUID(), proposal: { ...scope.proposal, linked_sub_rule_ids: event.target.checked ? [...scope.proposal.linked_sub_rule_ids, item.sub_rule_id] : scope.proposal.linked_sub_rule_ids.filter(id => id !== item.sub_rule_id) } })} /><span>{item.name}<small>当前：{item.current_standard_field || '未映射'} · 样例：{item.samples.join('、') || '无非空样例'}</small>{!item.selectable && <small className="mapping-warning">{item.disabled_reason === 'mapping_source_not_editable' || !item.conflict_source_path ? '该字段不能修改，不能联动。' : '目标已被 ' + item.conflict_source_path + ' 占用，不能联动。'}</small>}</span></label>)}</div>
      {editError && <p className="mapping-error" role="alert">{editError}</p>}
      <div className="mapping-actions"><button className="button-text" data-dialog-cancel onClick={cancelScope} disabled={saving}>{scope.kind === 'replacement' ? '取消替换' : '仅保留当前子规则'}</button><button className="button-text" onClick={() => void confirmScope()} disabled={saving || revisionConflict}>{scope.kind === 'replacement' ? '确认替换并保存' : '保存所选联动'}</button></div>
    </MappingDialog>}
  </section>
}
