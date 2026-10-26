import { type ReactNode } from 'react'
import { type Artifact, type Conversation, type FieldChangeSummary, type FieldMappingArtifact, type FileRecord, type Message, type Run } from './api'
import { businessName } from './BusinessWorkspace'
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
  canOperate: boolean
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

/** 对话时间线：按轮次连续展示输入、回复与产物；历史无关联内容单独归组，不伪造用户需求。 */
export function ConversationTimeline({ conversation, actions, renderers }: {
  conversation: Conversation
  actions: TimelineActions
  renderers: {
    mappingSummary: (artifact: FieldMappingArtifact) => ReactNode
    businessCard: (artifact: Artifact) => ReactNode
    classificationCard: (artifact: Extract<Artifact, { kind: 'log_classification' }>) => ReactNode
  }
}) {
  const { turns, unlinked } = buildTurns(conversation)
  const renderArtifact = (artifact: Artifact) => artifact.kind === 'field_mapping' ? renderers.mappingSummary(artifact) : artifact.kind === 'log_classification' ? renderers.classificationCard(artifact) : renderers.businessCard(artifact)
  return <div className="timeline">
    {conversation.messages.length === 0 && conversation.files.length === 0 && <div className="empty-state compact"><h2>这段会话还没有内容</h2><p>发送消息或上传文件，工作台会在这里显示进展。</p></div>}
    {turns.map(({ message, artifacts, fieldChanges, runs }) => <div className="timeline-item" key={message.id} id={'message-' + message.id}>
      {message.kind === 'file'
        ? <FileMessageCard message={message} conversation={conversation} actions={actions} />
        : message.kind === 'operation'
          ? <OperationCard message={message} runs={runs} actions={actions} />
          : <article className={'message ' + (message.actor === 'user' ? 'from-user' : '')}><div className="message-head"><strong>{message.actor === 'user' ? '你' : 'ToolWithAgent'}</strong><time>{readableTime(message.created_at)}</time></div><p>{message.content}</p>{artifacts.map(artifact => <div className="timeline-attached" key={artifact.id}>{renderArtifact(artifact)}</div>)}{fieldChanges.map(change => <div className="timeline-attached" key={change.run_id}><FieldChangeCard change={change} actions={actions} /></div>)}{message.run_id && <button className="button-text" onClick={() => actions.onOpenRun(message.run_id!)}>查看本次执行</button>}</article>}
    </div>)}
    {(unlinked.files.length > 0 || unlinked.artifacts.length > 0 || unlinked.fieldChanges.length > 0 || unlinked.runs.length > 0) && <details className="activity-section unlinked-inputs" aria-label="历史独立操作"><summary>历史独立操作 · {unlinked.files.length + unlinked.artifacts.length + unlinked.fieldChanges.length + unlinked.runs.length} 项（早于输入留痕，未关联具体输入）</summary>{unlinked.files.length > 0 && <section><h2>输入文件</h2>{unlinked.files.map(file => <FileRow key={file.id} file={file} actions={actions} />)}</section>}{unlinked.artifacts.map(artifact => <div className="timeline-attached" key={artifact.id}>{renderArtifact(artifact)}</div>)}{unlinked.fieldChanges.map(change => <div className="timeline-attached" key={change.run_id}><FieldChangeCard change={change} actions={actions} /></div>)}{unlinked.runs.length > 0 && <section><h2>执行记录</h2>{unlinked.runs.map(run => <button className="run-row" key={run.id} onClick={() => actions.onOpenRun(run.id)}><span className="run-label">{businessName(run.kind || run.type || '')}</span><StatusText status={run.status} className="run-status" /><span className="run-detail">执行详情 ›</span></button>)}</section>}</details>}
  </div>
}
