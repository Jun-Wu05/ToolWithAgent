import { useEffect, useRef, useState } from 'react'
import { api, type FieldChangeSummary, type FieldChangePreview, type FieldDeleteConfirmation } from './api'
import { MappingDialog } from './MappingDialog'
import { businessName } from './BusinessWorkspace'

const stateText: Record<string, string> = { ready: '待应用', applying: '应用中', applied: '已应用', undone: '已撤销', cancelled: '已取消' }
const groupText: Record<string, string> = { applied: '已应用', not_applied_by_user: '用户未应用', selected: '已选择', not_selected: '未选择' }
const valueText = (value: unknown) => value == null ? '无' : JSON.stringify(value, null, 2)

export function FieldChangesWorkspace({ summary, editable, onBack, onRefresh, onExecution }: {
  summary: FieldChangeSummary; editable: boolean; onBack: () => void; onRefresh: () => Promise<void>; onExecution: (id: string) => void
}) {
  const [preview, setPreview] = useState<FieldChangePreview | null>(null)
  const [rule, setRule] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [confirmation, setConfirmation] = useState<FieldDeleteConfirmation | null>(null)
  const live = useRef(true)
  const request = useRef(0)
  const receipt = useRef<{payload: string; key: string} | null>(null)
  const selectionReceipt = useRef<{payload: string; key: string} | null>(null)
  const confirmReceipt = useRef<{revision: number; key: string} | null>(null)
  const load = async () => {
    setError('')
    const version = ++request.current
    try { const result = await api.fieldPreview(summary.run_id); if (live.current && version === request.current) setPreview(result) }
    catch (caught) { if (live.current && version === request.current) setError(caught instanceof Error ? caught.message : '变更加载失败，请重新加载。') }
  }
  useEffect(() => {
    live.current = true
    const version = ++request.current
    void api.fieldPreview(summary.run_id).then(result => { if (live.current && version === request.current) setPreview(result) }).catch(caught => { if (live.current && version === request.current) setError(caught.message) })
    return () => { live.current = false; ++request.current }
  }, [summary.run_id, summary.revision, summary.status, summary.undo_run_id])
  const waitFor = async (id: string) => {
    while (live.current) {
      const result = await api.run(id)
      if (!live.current) return false
      if (result.status === 'succeeded') return true
      if (['failed', 'cancelled'].includes(result.status)) throw new Error(result.error_message || '变更未发布，请重新加载后检查或重试。')
      await new Promise(resolve => setTimeout(resolve, 750))
    }
    return false
  }
  const perform = async (undo = false, token?: string) => {
    if (!preview || busy) return
    setBusy(true); setError('')
    try {
      const payload = JSON.stringify([undo, preview.revision, token, preview.applied_artifact_id])
      if (receipt.current?.payload !== payload) receipt.current = {payload, key: crypto.randomUUID()}
      const result = undo ? await api.undoFields(preview.applied_artifact_id!, receipt.current.key)
        : await api.applyFields(preview.run_id, preview.revision, receipt.current.key, token)
      if (!live.current) return
      setConfirmation(null)
      if (await waitFor(result.run.id)) { await onRefresh(); if (live.current) onBack() }
    } catch (caught) { if (live.current) {await load(); if (live.current) setError(caught instanceof Error ? caught.message : '变更未能提交，请重试。')} }
    finally { if (live.current) setBusy(false) }
  }
  const select = async (id: string, checked: boolean) => {
    if (!preview || busy) return
    const version = ++request.current
    const ids = preview.groups.filter(group => group.id === id ? checked : preview.selected_group_ids.includes(group.id)).map(group => group.id)
    setBusy(true); setError(''); setConfirmation(null)
    const payload = JSON.stringify([preview.revision, ids])
    if (selectionReceipt.current?.payload !== payload) selectionReceipt.current = {payload, key: crypto.randomUUID()}
    try { const result = await api.selectFields(preview.run_id, preview.revision, ids, selectionReceipt.current.key); if (live.current && version === request.current) setPreview(result) }
    catch (caught) { if (live.current && version === request.current) setError(caught instanceof Error ? caught.message : '选择未保存，请重新加载。') }
    finally { if (live.current) setBusy(false) }
  }
  const apply = async () => {
    if (!preview || busy) return
    if (!preview.groups.some(group => preview.selected_group_ids.includes(group.id) && group.deletes.length)) { await perform(); return }
    setBusy(true); setError('')
    if (confirmReceipt.current?.revision !== preview.revision) confirmReceipt.current = {revision: preview.revision, key: crypto.randomUUID()}
    try { const item = await api.confirmFieldDeletion(preview.task_id, preview.revision, confirmReceipt.current.key); if (live.current) setConfirmation(item) }
    catch (caught) { if (live.current) setError(caught instanceof Error ? caught.message : '确认信息加载失败，请重试。') }
    finally { if (live.current) setBusy(false) }
  }
  const cancel = async () => {
    if (busy || !preview) return
    setBusy(true); setError('')
    try {
      const payload = 'cancel:' + preview.revision
      if (receipt.current?.payload !== payload) receipt.current = {payload, key: crypto.randomUUID()}
      await api.cancelFields(summary.run_id, preview.revision, receipt.current.key); if (!live.current) return; await onRefresh(); if (live.current) onBack() }
    catch (caught) { if (live.current) setError(caught instanceof Error ? caught.message : '取消失败，请重试。') }
    finally { if (live.current) setBusy(false) }
  }
  const rules = [...new Map(preview?.groups.flatMap(group => group.changes.map(item => [item.sub_rule_id, item.sub_rule_name] as const))).entries()]
  const currentRule = rules.some(([id]) => id === rule) ? rule : rules[0]?.[0]
  const writable = editable && preview?.status === 'ready' && preview.current
  return <section className="field-workspace" aria-label="字段变更预览">
    <header className="field-heading"><div><h2>字段变更</h2><p>{stateText[preview?.status || summary.status] || '正在加载'} · 同组操作一起应用</p></div><button className="button-secondary" onClick={onBack} disabled={busy}>返回对话</button></header>
    {error && <p className="mapping-error" role="alert">{error}<button className="button-text" onClick={() => void load()} disabled={busy}>重新加载变更</button></p>}
    {!preview && !error && <p role="status">正在加载变更…</p>}
    {preview && <>
      {!preview.current && preview.status === 'ready' && <p className="mapping-warning" role="status">输入或配置已变化。可查看旧变更，请取消后重新发起。</p>}
      {rules.length > 0 && <div className="field-tabs" role="tablist" aria-label="子规则">{rules.map(([id, name], index) => <button type="button" role="tab" id={'field-tab-' + index} aria-controls="field-rules" aria-selected={currentRule === id} tabIndex={currentRule === id ? 0 : -1} key={id} onClick={() => setRule(id)} onKeyDown={event => {
        let target = index
        if (event.key === 'ArrowRight') target = (index + 1) % rules.length
        else if (event.key === 'ArrowLeft') target = (index + rules.length - 1) % rules.length
        else if (event.key === 'Home') target = 0
        else if (event.key === 'End') target = rules.length - 1
        else return
        event.preventDefault(); setRule(rules[target][0]); document.getElementById('field-tab-' + target)?.focus()
      }}>{name}</button>)}</div>}
      <div id="field-rules" role="tabpanel" aria-labelledby={'field-tab-' + rules.findIndex(([id]) => id === currentRule)}>
        {preview.groups.filter(group => group.changes.some(item => item.sub_rule_id === currentRule) || !group.changes.length).map(group => <article className="field-group" key={group.id}>
          <div className="field-group-heading"><label><input type="checkbox" checked={preview.selected_group_ids.includes(group.id)} disabled={!writable || busy} onChange={event => void select(group.id, event.target.checked)} />{group.fields.join('、')}</label><span>{groupText[group.status] || group.status}</span></div>
          {group.changes.some(item => item.sub_rule_id !== currentRule) && <p className="mapping-hint">此组还影响其他子规则，选择将一起保存。</p>}
          {group.changes.filter(item => item.sub_rule_id === currentRule).map((item, index) => <div className={'field-change field-' + item.kind} key={index}><strong>{{add: '添加', modify: '修改', delete: '删除'}[item.kind]}：{item.field}</strong><details><summary>查看变更前后</summary><div className="field-values"><div><h3>变更前</h3><pre>{valueText(item.before)}</pre></div><div><h3>变更后</h3><pre>{valueText(item.after)}</pre></div></div></details></div>)}
          {!group.changes.length && <p>没有需要修改的字段。</p>}
        </article>)}
        {!preview.groups.length && <p>没有字段变更，请返回对话补充要求。</p>}
      </div>
      <footer className="mapping-actions">{writable && <button className="button-primary" onClick={() => void apply()} disabled={busy}>{busy ? '处理中…' : '应用所选变更并继续'}</button>}{editable && preview.status === 'ready' && <button className="button-secondary" onClick={() => void cancel()} disabled={busy}>取消本次变更</button>}{editable && preview.status === 'applied' && preview.applied_artifact_id && !preview.undo_run_id && <button className="button-secondary" onClick={() => void perform(true)} disabled={busy}>撤销本次变更</button>}<button className="button-text" onClick={() => onExecution(preview.undo_run_id || preview.apply_run_id || preview.run_id)}>查看执行详情</button></footer>
    </>}
    {confirmation && <MappingDialog title="确认删除字段" onClose={() => {if (!busy) setConfirmation(null)}}><p>将删除：{confirmation.payload.deletes.join('、')}。</p><p>所选变更将一次性应用，任一组失败全部回滚。</p>{confirmation.payload.downstream.length ? <ul>{confirmation.payload.downstream.map(item => <li key={item.id}>{businessName(item.kind)} 版本 <span className="num">{item.version}</span> 将过期</li>)}</ul> : <p>没有已发布的下游产物受影响。</p>}<div className="mapping-actions"><button className="button-secondary" data-dialog-cancel onClick={() => setConfirmation(null)} disabled={busy}>返回检查</button><button className="button-danger" onClick={() => void perform(false, confirmation.token)} disabled={busy}>确认删除并应用</button></div></MappingDialog>}
  </section>
}
