import { useEffect, useRef, useState } from 'react'
import { api, type Artifact, type Confirmation, type Conversation, type OperationInput, type Run, type ProgressSummary } from './api'
import { LogClassificationResult } from './LogClassificationResult'

export const businessName = (kind: string) => ({log_classification: '日志类型提取', log_parse: '日志类型提取', file_ingest: '文件校验', file_upload: '上传文件', enum_extract: '枚举提取', fill: '填充值映射', remove_mapping: '取消值映射', export: '规则导出', enum_values: '枚举提取', threat_mapping: '威胁类型映射', field_mapping: '标准字段映射', config_export: '规则导出', business: '业务处理', business_operation: '业务处理', user_request: '业务任务', business_clear: '清空业务数据', mapping_draft_apply: '应用映射修改', field_change_apply: '应用字段变更', field_change_undo: '撤销字段变更', log_knowledge_submit: '日志知识申请'}[kind] || '业务处理')
export function BusinessOperations({conversation, source, onDone}: {conversation: Conversation; source?: Artifact; onDone: () => Promise<void>}) {
  const facts = conversation.session_facts
  const [kind, setKind] = useState<OperationInput['step']['type']>(source?.kind === 'enum_values' ? 'threat_mapping' : source?.kind === 'threat_mapping' ? 'fill' : source?.kind === 'field_mapping' || source?.kind === 'log_classification' ? 'export' : 'enum_extract')
  // 分类导出本轮固定入口规则；子规则导出待标准字段映射后续轮次再开放。
  const rulePart: 'entry_rules' | 'sub_rules' = source?.kind === 'log_classification' ? 'entry_rules' : 'sub_rules'
  const [field, setField] = useState('')
  const [configId, setConfigId] = useState(source?.kind === 'field_mapping' ? source.id : '')
  const [sourceId, setSourceId] = useState(source?.kind === 'enum_values' || source?.kind === 'threat_mapping' ? source.id : '')
  const [values, setValues] = useState('')
  const [direct, setDirect] = useState(false)
  const [fillKind, setFillKind] = useState<'enum' | 'threat'>(source?.kind === 'threat_mapping' ? 'threat' : 'enum')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const live = useRef(true)
  const receipt = useRef<{payload: string; key: string} | null>(null)
  useEffect(() => { live.current = true; return () => { live.current = false } }, [])
  const configs = (conversation.artifacts || []).filter(item => item.kind === 'field_mapping' && item.current && item.config_ref && facts?.available_config_refs.includes(item.config_ref))
  const config = configs.find(item => item.id === configId)
  const sources = (conversation.artifacts || []).filter(item => (item.kind === 'enum_values' || item.kind === 'threat_mapping') && item.current)
  const selected = sources.find(item => item.id === sourceId)
  const reference = facts?.referenceable_artifacts.find(item => item.artifact_type === selected?.kind)
  const configRef = config?.kind === 'field_mapping' ? config.config_ref : facts?.available_config_refs.includes(configId) ? configId : undefined
  const needConfig = ['fill', 'remove_mapping', 'export'].includes(kind) && source?.kind !== 'log_classification'
  const targets = fillKind === 'enum' ? facts?.enum_mapping_target_fields || [] : reference?.target_bindings.filter(item => item.config_ref === configRef && item.target_field === '威胁类型').map(item => item.target_field) || []
  const valid = !!facts && (!source || (source.kind === 'log_classification' ? source.mapping_eligible : 'current' in source && source.current)) && (!needConfig || !!configRef) && (kind !== 'enum_extract' || (!!facts.has_logs && !!field)) && (kind !== 'remove_mapping' || !!field) && (kind !== 'fill' || (targets.includes(field) && (fillKind === 'enum' || selected?.kind === 'threat_mapping'))) && (kind !== 'threat_mapping' || (direct ? !!values.trim() : selected?.kind === 'enum_values' && !!reference))
  return <form className="mapping-form" aria-label="后处理操作" onSubmit={event => {
    event.preventDefault(); if (!valid || busy) return
    const step: OperationInput['step'] = {step_id: 'operation', type: kind}
    const input: OperationInput = {step}
    if (kind === 'enum_extract') {step.target_field = field; step.source_ref = 'session.logs'}
    if (kind === 'threat_mapping') {step.source_ref = direct ? 'user.values' : reference?.source_ref; if (direct) step.values = values.split(/\r?\n/).map(item => item.trim()).filter(Boolean); else input.source_artifact_id = sourceId}
    if (needConfig && config) input.config_artifact_id = configId
    if (kind === 'fill') {step.fill_kind = fillKind; step.target_fields = [field]; step.config_ref = configRef; step.source_ref = fillKind === 'enum' ? 'session.enum_mapping_table' : reference?.source_ref; if (fillKind === 'threat') input.source_artifact_id = sourceId}
    if (kind === 'remove_mapping') {step.target_fields = [field]; step.config_ref = configRef}
    if (kind === 'export') {step.source_ref = source?.kind === 'log_classification' ? 'session.log_classification.' + rulePart : configRef; if (source?.kind === 'log_classification') input.source_artifact_id = source.id}
    const payload = JSON.stringify(input)
    if (receipt.current?.payload !== payload) receipt.current = {payload, key: crypto.randomUUID()}
    setBusy(true); setError('')
    void api.operation(conversation.id, input, receipt.current.key).then(async () => { if (live.current) {await onDone(); if (live.current) receipt.current = null} }).catch(caught => {if (live.current) setError(caught instanceof Error ? caught.message : '操作未能启动，请重试。')}).finally(() => {if (live.current) setBusy(false)})
  }}>
    <label>处理方式<select value={kind} onChange={event => {setKind(event.target.value as typeof kind); setField('')}} disabled={busy}>{!source && <option value="enum_extract">提取枚举</option>}{(!source || source.kind === 'enum_values') && <option value="threat_mapping">映射威胁类型</option>}{(!source || source.kind === 'field_mapping' || source.kind === 'threat_mapping') && <option value="fill">填充值映射</option>}{(!source || source.kind === 'field_mapping') && <><option value="remove_mapping">取消值映射</option><option value="export">导出规则</option></>}{source?.kind === 'log_classification' && <option value="export">导出规则</option>}</select></label>
    {/* 分类导出本轮只出入口规则；子规则导出待标准字段映射后续轮次再开放。 */}
    {needConfig && <label>目标配置<select aria-label="目标配置" value={configId} onChange={event => {setConfigId(event.target.value); setField('')}} disabled={busy || source?.kind === 'field_mapping'}><option value="">请选择当前配置</option>{configs.map(item => <option key={item.id} value={item.id}>{item.kind === 'field_mapping' && item.config_ref === 'session.decoded_config' ? '上传规则' : '日志生成配置'}（{item.id}）</option>)}{facts?.available_config_refs.filter(ref => !configs.some(item => item.kind === 'field_mapping' && item.config_ref === ref)).map(ref => <option key={ref} value={ref}>{ref === 'session.decoded_config' ? '上传规则' : '日志生成配置'}</option>)}</select></label>}
    {kind === 'fill' && <label>映射来源<select value={fillKind} onChange={event => {setFillKind(event.target.value as typeof fillKind); setField('')}} disabled={busy || source?.kind === 'threat_mapping'}><option value="enum">枚举映射附件</option><option value="threat">威胁映射结果</option></select></label>}
    {kind === 'threat_mapping' && <label>值来源<select value={direct ? 'direct' : 'artifact'} onChange={event => setDirect(event.target.value === 'direct')} disabled={busy || source?.kind === 'enum_values'}><option value="artifact">枚举结果</option><option value="direct">直接输入原始值</option></select></label>}
    {kind === 'threat_mapping' && direct ? <label>原始值（每行一个）<textarea value={values} onChange={event => setValues(event.target.value)} disabled={busy} /></label> : (kind === 'threat_mapping' || (kind === 'fill' && fillKind === 'threat')) && <label>来源结果<select aria-label="来源结果" value={sourceId} onChange={event => setSourceId(event.target.value)} disabled={busy || source?.kind === 'enum_values' || source?.kind === 'threat_mapping'}><option value="">请选择当前结果</option>{sources.filter(item => item.kind === (kind === 'threat_mapping' ? 'enum_values' : 'threat_mapping')).map(item => <option key={item.id} value={item.id}>{businessName(item.kind)}（{item.id}）</option>)}</select></label>}
    {['enum_extract', 'remove_mapping'].includes(kind) && <label>目标字段<input aria-label="目标字段" value={field} onChange={event => setField(event.target.value)} disabled={busy} placeholder="填写明确字段名称" required /></label>}
    {kind === 'fill' && <label>目标字段<select aria-label="目标字段" value={field} onChange={event => setField(event.target.value)} disabled={busy}><option value="">请选择字段</option>{targets.map(item => <option key={item} value={item}>{item}</option>)}</select></label>}
    {conversation.session_facts_error && <p className="mapping-error" role="alert">当前业务输入不可用，请重新加载或重新上传主数据。</p>}
    {error && <p className="mapping-error" role="alert">{error}</p>}<button className="button-secondary" disabled={busy || !valid}>{busy ? '启动中…' : '开始处理'}</button>
  </form>
}

export function BusinessConfirmation({run, onResolved, beforeSend = false, onBack}: {run: Run; onResolved: () => Promise<void>; beforeSend?: boolean; onBack: () => void}) {
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const live = useRef(true)
  const receipt = useRef(crypto.randomUUID())
  useEffect(() => {live.current = true; api.confirmationToken(run.id).then(item => {if (live.current) setConfirmation(item)}).catch(caught => {if (live.current) setError(caught.message)}); return () => {live.current = false}}, [run.id])
  const resolve = async (confirm: boolean) => {
    if (busy || (confirm && !confirmation)) return
    setBusy(true); setError('')
    try {
      if (confirm) await api.confirmRun(run.id, confirmation!, receipt.current)
      else {const item = await api.cancelToken(run.id); if (!live.current) return; await api.cancelRun(run.id, item.token)}
      if (!live.current) return
      if (beforeSend) {
        let result = await api.run(run.id)
        while (!['succeeded', 'cancelled', 'failed'].includes(result.status)) {
          if (result.status === 'waiting_confirmation') throw new Error('仍有待确认事项，请返回处理后再发送。')
          await new Promise(resolve => setTimeout(resolve, 1000)); if (!live.current) return; result = await api.run(run.id)
        }
        if (confirm && result.status !== 'succeeded') throw new Error(result.error_message || '执行未成功，消息尚未发送。')
        if (!confirm && result.status !== 'cancelled') throw new Error('取消尚未完成，消息尚未发送。')
      }
      if (live.current) await onResolved()
    } catch (caught) {if (live.current) setError(caught instanceof Error ? caught.message : '方案处理失败，输入已保留。')}
    finally {if (live.current) setBusy(false)}
  }
  return <section className="result-card" aria-label="执行方案确认"><h3>{confirmation?.payload.reason_code === 'recovery_exhausted' ? '确认继续执行' : '确认执行方案'}</h3>{confirmation?.payload.reason_code === 'recovery_exhausted' && <p>自动恢复次数已用完。确认后只重试未完成步骤，已完成结果会保留。</p>}<p>{confirmation?.payload.question || '正在加载确认事项…'}</p>{confirmation?.payload.choices?.length ? <p>可选处理：{confirmation.payload.choices.join('、')}</p> : null}{confirmation?.payload.operations && <p>将执行：{confirmation.payload.operations.map(operation => typeof operation === 'string' ? businessName(operation) : '业务处理').join('、')}。</p>}{error && <p role="alert" className="mapping-error">{error}</p>}<div className="mapping-actions"><button className="button-text" onClick={onBack} disabled={busy}>返回处理</button><button className="button-text" onClick={() => void resolve(true)} disabled={busy || !confirmation}>{beforeSend ? '确认完成后发送' : '确认执行'}</button><button className="button-text" onClick={() => void resolve(false)} disabled={busy}>{beforeSend ? '取消后发送' : '取消执行'}</button></div></section>
}

export function ArtifactValues({artifact, content}: {artifact: Artifact; content: Record<string, unknown>}) {
  if (artifact.kind === 'log_classification') return <LogClassificationResult key={artifact.id} content={content} />
  if (artifact.kind === 'enum_values' && Array.isArray(content.values)) return <section aria-label="枚举值"><p>提取字段：{typeof content.field === 'string' ? content.field : '未指定'}</p><ul>{content.values.map((value, index) => <li key={index}>{String(value)}</li>)}</ul>{typeof content.regex === 'string' && <details><summary>提取正则</summary><pre className="artifact-content">{content.regex}</pre></details>}</section>
  if (artifact.kind === 'threat_mapping' && Array.isArray(content.mappings)) return <div className="mapping-table-region"><table className="artifact-values"><thead><tr><th>原始值</th><th>标准威胁类型</th><th>映射方式</th></tr></thead><tbody>{content.mappings.map((row, index) => <tr key={index}><td>{String(row.original_value ?? '')}</td><td>{String(row.mapped_value ?? '')}</td><td>{row.mapping_type === 'REGULAR' ? '正则' : '相等'}</td></tr>)}</tbody></table></div>
  return <pre className="artifact-content">{artifact.kind === 'config_export' && typeof content.content === 'string' ? content.content : JSON.stringify(content, null, 2)}</pre>
}

export const phaseName: Record<string, string> = {planning: '规划任务', retrieval: '检索依据', model_call: '业务分析', validation: '校验结果', writeback: '写入结果', execution: '执行步骤', completed: '步骤完成'}
export const pipelineStageName: Record<string, string> = {format_identification: '格式识别', feature_location: '特征定位', kv_feature_identifier: 'KV 特征生成', classification: '日志分类', sample_fill: '样本填充'}
export const pipelineErrorName: Record<string, string> = {format_invalid: '格式识别结果无效', feature_location_failed: '特征定位失败', kv_feature_identifier_failed: 'KV 特征生成失败', classification_failed: '日志分类失败', sample_fill_failed: '样本填充失败'}
const progressName: Record<string, string> = {running: '进行中', success: '已完成', failed: '失败'}
export function progressLabel(summary?: ProgressSummary) {
  if (!summary || !phaseName[summary.phase || '']) return ''
  const stage = pipelineStageName[summary.pipeline_stage || ''] || phaseName[summary.phase || '']
  const base = `${businessName(summary.operation || '')}：${stage} ${progressName[summary.progress_status || ''] || ''}`.trimEnd()
  const batch = summary.current_batch && summary.total_batches ? ` 第 ${summary.current_batch}/${summary.total_batches} 批` : ''
  const elapsed = summary.elapsed_seconds ? ` · 已耗时 ${Math.round(summary.elapsed_seconds)} 秒` : ''
  const reason = summary.error_code ? ` · ${pipelineErrorName[summary.error_code] || summary.error_code}` : ''
  return base + batch + elapsed + reason
}
export function RunProgress({run}: {run: Run}) {
  const events = (run.events || []).filter(item => item.event_type === 'run_progress' && progressLabel(item.summary))
  const scopes = [...new Set(events.map(item => item.scope_id))]
  return events.length ? <section aria-label="执行步骤"><h3>执行步骤</h3><ol className="run-progress">{events.map(item => <li key={item.sequence}><span>{progressLabel(item.summary)}</span>{item.summary?.dependency_scope_ids?.length ? <small>依赖：{item.summary.dependency_scope_ids.map(scope => scopes.includes(scope) ? `步骤 ${scopes.indexOf(scope) + 1}` : '前序步骤').join('、')}</small> : null}</li>)}</ol></section> : null
}
