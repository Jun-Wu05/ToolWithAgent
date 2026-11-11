import { useEffect, useState, type ReactNode } from 'react'
import { api, type Artifact, type Conversation, type FieldChangeSummary, type FieldMappingArtifact, type FileRecord, type Message, type Run, type RunEvent, type Suggestion } from './api'
import { businessName, phaseName, pipelineStageName, pipelineErrorName } from './BusinessWorkspace'
import { StatusText } from './VisualPrimitives'

const statusName: Record<string, string> = {
  queued: '排队中', pending: '排队中', running: '运行中', succeeded: '已完成',
  waiting_confirmation: '待确认', completed: '已完成', failed: '失败', cancelled: '已取消'
}
const readableTime = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''
const usageName = (role?: string) => role === 'enum_mapping' ? '枚举映射附件' : '主数据'
const sizeText = (size?: number) => size != null ? (size / 1024).toFixed(1) + ' KB' : '已上传'

export type Turn = {
  message: Message
  artifacts: Artifact[]
  fieldChanges: FieldChangeSummary[]
  runs: Run[]
}

export type UnlinkedInputs = { files: FileRecord[]; artifacts: Artifact[]; fieldChanges: FieldChangeSummary[]; runs: Run[] }

/** 按消息建立轮次：输入记录、回复、产物与 Run 全部经稳定标识关联；时间相同按 id 稳定排序，不按相邻时间猜测。 */
export function buildTurns(conversation: Conversation): { turns: Turn[]; unlinked: UnlinkedInputs } {
  const messages = [...conversation.messages].sort((left, right) => (left.created_at || '').localeCompare(right.created_at || '') || left.id.localeCompare(right.id))
  const turns = messages.map(message => ({ message, artifacts: [] as Artifact[], fieldChanges: [] as FieldChangeSummary[], runs: [] as Run[] }))
  const byId = new Map(turns.map(turn => [turn.message.id, turn]))
  const byRunId = new Map(turns.filter(turn => turn.message.run_id).map(turn => [turn.message.run_id!, turn]))
  const linkedFileIds = new Set(messages.flatMap(message => (message.kind === 'file' && message.payload?.file_id) ? [String(message.payload.file_id)] : []))
  const linkedRunIds = new Set(messages.flatMap(message => message.run_id ? [message.run_id] : []))
  for (const artifact of conversation.artifacts || []) {
    const turn = 'result_message_id' in artifact && artifact.result_message_id ? byId.get(artifact.result_message_id) : undefined
    if (turn) turn.artifacts.push(artifact)
  }
  for (const change of conversation.field_changes || []) {
    const turn = change.run_id ? byRunId.get(change.run_id) : undefined
    if (turn) turn.fieldChanges.push(change)
  }
  for (const run of conversation.runs) {
    const turn = (run.message_id ? byId.get(run.message_id) : undefined) || (run.id ? byRunId.get(run.id) : undefined)
    if (turn) turn.runs.push(run)
  }
  const linkedArtifactIds = new Set(turns.flatMap(turn => turn.artifacts.map(artifact => artifact.id)))
  const linkedChangeRunIds = new Set(turns.flatMap(turn => turn.fieldChanges.map(change => change.run_id)))
  const unlinked: UnlinkedInputs = {
    files: conversation.files.filter(file => !linkedFileIds.has(file.id)),
    artifacts: (conversation.artifacts || []).filter(artifact => !linkedArtifactIds.has(artifact.id)),
    fieldChanges: (conversation.field_changes || []).filter(change => !linkedChangeRunIds.has(change.run_id)),
    runs: conversation.runs.filter(run => !linkedRunIds.has(run.id) && !(run.message_id && byId.has(run.message_id)) && !linkedChangeRunIds.has(run.id)),
  }
  return { turns, unlinked }
}

export const operationParamText = (payload: Record<string, unknown>) => {
  const parts: string[] = []
  if (typeof payload.feature_field === 'string' && payload.feature_field) parts.push(`分类特征字段 ${payload.feature_field}`)
  if (typeof payload.product === 'string') parts.push(`产品 ${payload.product}`)
  if (typeof payload.log_vendor === 'string') parts.push(`厂商 ${payload.log_vendor}`)
  if (typeof payload.data_source === 'string' && payload.data_source) parts.push(`数据源 ${payload.data_source}`)
  const step = payload.step
  if (step && typeof step === 'object') {
    const spec = step as Record<string, unknown>
    if (typeof spec.target_field === 'string') parts.push(`目标字段 ${spec.target_field}`)
    if (Array.isArray(spec.target_fields)) parts.push(`目标字段 ${spec.target_fields.join('、')}`)
    if (spec.fill_kind === 'enum') parts.push('来源：枚举映射附件')
    if (spec.fill_kind === 'threat') parts.push('来源：威胁映射结果')
  }
  if (payload.source_artifact_id || payload.classification_artifact_id) parts.push('来源：已有结果')
  if (payload.config_artifact_id) parts.push('目标配置：已选当前结果')
  return parts.join(' · ')
}

export type TimelineActions = {
  onOpenRun: (runId: string) => void
  onParseLog: (file: FileRecord) => void
  onFeatureField: (fileId: string, value: string) => void
  featureFields: Record<string, string>
  actionBusy: string | null
  onMappingSource: (source: { id: string; kind: 'file' | 'classification'; label: string }) => void
  mappingForm: (source: { id: string; kind: 'file' | 'classification'; label: string }) => ReactNode
  onOpenFieldChanges: (runId: string) => void
  onSuggestion?: (suggestion: Suggestion, message: Message) => void
  canOperate: boolean
}

/** 助手消息内的下一步建议芯片（#435）：动作接既有 API，prompt 只填输入框。 */
export function SuggestionChips({ message, actions }: { message: Message; actions: TimelineActions }) {
  const raw = message.payload?.suggestions
  const suggestions = Array.isArray(raw) ? raw as Suggestion[] : []
  if (!suggestions.length || !actions.onSuggestion) return null
  return <div className="suggestion-chips" role="group" aria-label="下一步建议">
    {suggestions.map((suggestion, index) => (
      <button key={suggestion.id + ':' + index} className="suggestion-chip" type="button"
        disabled={!!actions.actionBusy && suggestion.type === 'action'}
        onClick={() => actions.onSuggestion?.(suggestion, message)}>{suggestion.label}</button>
    ))}
  </div>
}

export function FileRow({ file, actions }: { file: FileRecord; actions: TimelineActions }) {
  const suffix = file.name.split('.').pop()?.toLowerCase() || ''
  const parseEligible = actions.canOperate && file.active !== false && file.role !== 'enum_mapping' && file.parse_status === 'succeeded' && ['txt', 'log', 'json', 'jsonl', 'csv', 'xlsx'].includes(suffix)
  const mappingEligible = actions.canOperate && file.active !== false && file.role !== 'enum_mapping' && file.mapping_eligible
  const source = { id: file.id, kind: 'file' as const, label: file.name }
  return <div className="file-row"><span className="file-icon">▤</span><div className="file-main"><strong>{file.name}</strong><small>{file.active === false ? '历史输入 · ' : ''}{usageName(file.role)} · {sizeText(file.size)}</small>{parseEligible && <div className="file-actions"><label>分类特征字段（可选）<input aria-label={file.name + ' 分类特征字段'} placeholder="自动识别" value={actions.featureFields[file.id] || ''} onChange={event => actions.onFeatureField(file.id, event.target.value)} disabled={!!actions.actionBusy} /></label><button className="button-secondary" onClick={() => actions.onParseLog(file)} disabled={!!actions.actionBusy}>{actions.actionBusy === file.id ? '启动中…' : '提取日志类型'}</button></div>}{mappingEligible && <><button className="button-secondary mapping-entry" onClick={() => actions.onMappingSource(source)} disabled={!!actions.actionBusy}>标准字段映射</button>{actions.mappingForm(source)}</>}</div><StatusText status={file.parse_status || ''} label={statusName[file.parse_status || ''] || '已登记'} className="file-status" /></div>
}

/** 操作记录卡：还原用户真实提交的业务动作与参数，不以用户口吻伪造文本。 */
function OperationCard({ message, runs, actions }: { message: Message; runs: Run[]; actions: TimelineActions }) {
  const payload = message.payload || {}
  const action = String(payload.action || '')
  const current = runs.find(run => ['queued', 'pending', 'running', 'waiting_confirmation'].includes(run.status)) || runs.at(-1)
  const params = operationParamText(payload)
  return <article className="message from-user operation-record" aria-label={'操作记录：' + businessName(action)}><div className="message-head"><strong>你</strong><time>{readableTime(message.created_at)}</time></div><p><span className="operation-badge">操作</span>{businessName(action)}</p>{params && <p className="operation-params">{params}</p>}{current && <div className="operation-status"><StatusText status={current.status} />{runs.length > 1 && <small>共 {runs.length} 次尝试</small>}<button className="button-text" onClick={() => actions.onOpenRun(current.id)}>查看执行详情</button></div>}</article>
}

function FileMessageCard({ message, conversation, actions }: { message: Message; conversation: Conversation; actions: TimelineActions }) {
  const fileId = String(message.payload?.file_id || '')
  const live = conversation.files.find(file => file.id === fileId)
  const file: FileRecord = live || { id: fileId, name: String(message.payload?.name || '附件'), size: typeof message.payload?.size === 'number' ? message.payload.size : undefined, role: message.payload?.role as FileRecord['role'], parse_status: 'queued' }
  return <article className="message from-user file-message" aria-label={'输入附件：' + file.name}><div className="message-head"><strong>你</strong><time>{readableTime(message.created_at)}</time></div><FileRow file={file} actions={actions} /></article>
}

function FieldChangeCard({ change, actions }: { change: FieldChangeSummary; actions: TimelineActions }) {
  return <article className="result-card"><strong>字段变更</strong><p>{{ ready: '待选择与应用', applying: '正在应用', applied: '已应用，可查看或撤销本次变更', undone: '已撤销，历史版本保留', cancelled: '已取消' }[change.status] || change.status}</p><button className="button-secondary" onClick={() => actions.onOpenFieldChanges(change.run_id)}>查看变更</button></article>
}

export type StepLine = { label: string; detail: string; failed: boolean }

/** 同一步骤的重复进度事件按 scope 合并取最新；末尾并入 Run 的真实失败原因，不逐条回放原始事件。 */
export function dedupeStepLines(events: RunEvent[], run: Run): StepLine[] {
  const latestByScope = new Map<string, RunEvent>()
  for (const event of events) {
    if (event.event_type === 'run_progress' && event.scope_id) latestByScope.set(event.scope_id + ':' + (event.summary?.pipeline_stage || ''), event)
  }
  const lines: StepLine[] = [...latestByScope.values()].map(event => {
    const summary = event.summary || {}
    const parts = [pipelineStageName[summary.pipeline_stage || ''] || phaseName[summary.phase || ''] || '']
    if (summary.current_batch && summary.total_batches) parts.push(`第 ${summary.current_batch}/${summary.total_batches} 批`)
    if (summary.elapsed_seconds) parts.push(`${Math.round(summary.elapsed_seconds)} 秒`)
    if (summary.error_code) parts.push(pipelineErrorName[summary.error_code] || summary.error_code)
    return {
      label: businessName(summary.operation || ''),
      detail: parts.filter(Boolean).join(' · '),
      failed: summary.progress_status === 'failed',
    }
  })
  if (run.status === 'failed' && run.error_message) {
    lines.push({ label: '失败原因', detail: run.error_message, failed: true })
  }
  return lines
}

function RunDisclosure({ run }: { run: Run }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<Run | null>(null)
  useEffect(() => {
    if (!open) return
    let live = true
    api.run(run.id).then(value => { if (live) setDetail(value) }).catch(() => { if (live) setDetail(null) })
    return () => { live = false }
  }, [open, run.id])
  const events = detail?.events || run.events || []
  const lines = dedupeStepLines(events, detail || run)
  if (!lines.length) return null
  const seconds = run.started_at && (run.finished_at || run.updated_at)
    ? Math.max(1, Math.round((new Date(run.finished_at || run.updated_at!).getTime() - new Date(run.started_at).getTime()) / 1000))
    : null
  return <div className="run-disclosure">
    <button className="run-disclosure-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>执行了 {lines.length} 步{seconds ? ` · ${seconds} 秒` : ''} {open ? '▾' : '▸'}</button>
    {open && <ol className="run-step-list">{lines.map((line, index) => <li key={index} className={'run-step' + (line.failed ? ' run-step-failed' : '')}><div><strong>{line.label}</strong>{line.detail && <span> · {line.detail}</span>}</div></li>)}</ol>}
  </div>
}

/** 对话时间线：按轮次连续展示输入、回复与产物；历史无关联内容单独归组，不伪造用户需求。 */
export function ConversationTimeline({ conversation, actions, renderers }: {
  conversation: Conversation
  actions: TimelineActions
  renderers: {
    mappingSummary: (artifact: FieldMappingArtifact) => ReactNode
    businessCard: (artifact: Artifact) => ReactNode
    classificationCard: (artifact: Extract<Artifact, { kind: 'log_classification' }>) => ReactNode
    paramsForm?: (message: Message, run: Run | undefined) => ReactNode
  }
}) {
  const { turns } = buildTurns(conversation)
  const renderArtifact = (artifact: Artifact) => artifact.kind === 'field_mapping' ? renderers.mappingSummary(artifact) : artifact.kind === 'log_classification' ? renderers.classificationCard(artifact) : renderers.businessCard(artifact)
  return <div className="timeline">
    {conversation.messages.length === 0 && conversation.files.length === 0 && <div className="empty-state compact"><h2>这段会话还没有内容</h2><p>发送消息或上传文件，工作台会在这里显示进展。</p></div>}
    {turns.map(({ message, artifacts, fieldChanges, runs }) => {
      const turnRun = message.run_id ? runs.find(run => run.id === message.run_id) || conversation.runs.find(run => run.id === message.run_id) : undefined
      const isUser = message.actor === 'user'
      return <div className={'chat-row' + (isUser ? ' chat-row-user' : '')} key={message.id} id={'message-' + message.id}>
        {message.kind === 'file'
          ? <FileMessageCard message={message} conversation={conversation} actions={actions} />
          : message.kind === 'operation'
            ? <OperationCard message={message} runs={runs} actions={actions} />
            : <div className={'chat-body'}><article className={'message ' + (isUser ? 'from-user' : '')}><div className="message-head"><strong>{isUser ? '你' : 'ToolWithAgent'}</strong><time>{readableTime(message.created_at)}</time></div><p>{message.content}</p>{!isUser && <SuggestionChips message={message} actions={actions} />}{artifacts.map(artifact => <div className="timeline-attached" key={artifact.id}>{renderArtifact(artifact)}</div>)}{fieldChanges.map(change => <div className="timeline-attached" key={change.run_id}><FieldChangeCard change={change} actions={actions} /></div>)}{turnRun && <div className="chat-run-row"><RunDisclosure run={turnRun} /><button className="button-text" onClick={() => actions.onOpenRun(turnRun.id)}>查看本次执行</button></div>}</article>{!isUser && renderers.paramsForm?.(message, turnRun)}</div>}
      </div>
    })}
  </div>
}
