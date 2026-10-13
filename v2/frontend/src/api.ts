export type Identity = { id: string; display_name: string; role: string }
export type ConversationSummary = { id: string; title: string; created_at: string; updated_at: string }
export type Message = { id: string; actor: string; content: string; created_at?: string }
export type FileRecord = { id: string; name: string; size?: number; parse_status?: string; mapping_eligible?: boolean; created_at?: string }
export type ClassificationArtifact = {
  id: string
  run_id: string
  file_id: string
  kind: 'log_classification'
  status: string
  summary: { log_types: { name: string; count: number }[]; coverage: { matched_lines: number; total_lines: number }; rule_summary: string }
  mapping_eligible?: boolean
  submission_eligible: boolean
  submission_status?: string
  application_id?: number
  created_at?: string
}
export type EventAnnotation = {
  rule_name: string; event_name: string; event_level: string; threat_source_field: string
  threat_types: string[]; status: 'judged' | 'uncertain'
}
export type MappingWarning = { code: 'threat_chain_warning'; message: string }
export type FieldMappingArtifact = {
  id: string; run_id: string; file_id: string; kind: 'field_mapping'; status: string; current: boolean
  source_artifact_id?: string; created_at?: string
  summary: { rule_count: number; field_count: number; matched_count: number; unmatched_count: number; parse_error_count: number; uncertain_annotation_count?: number; warning_codes?: MappingWarning['code'][] }
}
export type MappingInput = { file_id?: string; classification_artifact_id?: string; product: string; log_vendor: string; data_source?: string }
export type MappingStatus = 'matched' | 'unmatched' | 'parse_error'
export type MappingView = {
  artifact_id: string; sub_rules: { id: string; name: string; field_count: number }[]; sub_rule_id: string
  items: { source_path: string; samples: string[]; expanded_samples: { value: string; line_number: number | null; source?: string }[];
    standard_field: string; evidence: string; status: MappingStatus; warning: string; user_modified: boolean }[]
  total: number; page: number; page_size: number; sample_line_reference: 'log_entry'
  event_annotations?: EventAnnotation[]; warnings?: MappingWarning[]
}
export type MappingQuery = { sub_rule?: string; page: number; q: string; status: string }
export type ArtifactDownload = { name: string; blob: Blob }
export type Run = { id: string; task_id?: string; file_id?: string; status: string; kind?: string; type?: string; error_code?: string | null; error_message?: string | null; created_at?: string; updated_at?: string }
export type Conversation = ConversationSummary & { messages: Message[]; files: FileRecord[]; runs: Run[]; artifacts?: (ClassificationArtifact | FieldMappingArtifact)[] }
export type EventRecord = { sequence: number; event_type: string; resource_type: string; resource_id: string; payload: Record<string, unknown> }
export type ApiError = Error & { code?: string; status?: number }
const base = '/api/v2'
const messages: Record<string, string> = {
  mapping_input_stale: '主数据或分类结果已变化，请重新选择当前输入。',
  mapping_input_required: '请选择一份当前输入后开始映射。',
  data_source_fields_required: '请填写产品和厂商。',
  invalid_source_fields: '产品、厂商或数据源格式无效，请检查后重试。',
  file_not_validated: '文件尚未校验成功，请等待校验完成。',
  artifact_not_found: '结果不存在或当前身份无权查看，请返回会话。',
  artifact_corrupt: '结果文件不可用，请重新执行映射。',
  invalid_mapping_query: '搜索或筛选条件无效，请修改后重试。',
  mapping_sub_rule_not_found: '子规则不存在，请重新选择。',
  insufficient_capability: '当前身份不能执行这项操作。',
  unauthenticated: '当前身份已失效，请重新选择身份。',
  idempotency_key_reused: '输入参数已变化，请重新开始映射。',
}
async function responseFor(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(base + path, { credentials: 'include', ...init })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = new Error(messages[body?.error?.code || body?.detail] || body?.error?.message || body?.detail || '请求失败，请稍后重试。') as ApiError
    error.code = body?.error?.code
    error.status = response.status
    throw error
  }
  return response
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await responseFor(path, init)).json() as Promise<T>
}
export function saveDownload(file: ArtifactDownload) {
  const url = URL.createObjectURL(file.blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.name
  document.body.append(link)
  try { link.click() } finally { link.remove(); URL.revokeObjectURL(url) }
}
async function mappingDownload(artifactId: string): Promise<ArtifactDownload> {
  const response = await responseFor('/artifacts/' + encodeURIComponent(artifactId) + '/download')
  const disposition = response.headers.get('Content-Disposition') || ''
  const encoded = disposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1]
  let name = disposition.match(/filename\s*=\s*"([^"]+)"/i)?.[1] || disposition.match(/filename\s*=\s*([^;]+)/i)?.[1]?.trim() || '字段映射_Base64.txt'
  if (encoded) { try { name = decodeURIComponent(encoded.trim()) } catch { /* Use the plain filename when encoding is invalid. */ } }
  name = name.split(/[\\/]/).pop()?.replace(/\p{Cc}/gu, '') || '字段映射_Base64.txt'
  return { name, blob: await response.blob() }
}
export const api = {
  me: () => request<Identity>('/me'),
  identities: () => request<{ items: Identity[] }>('/dev/identities'),
  selectIdentity: (user_id: string) => request<Identity>('/dev/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id }) }),
  conversations: () => request<{ items: ConversationSummary[] }>('/conversations'),
  createConversation: () => request<ConversationSummary>('/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }),
  conversation: (id: string) => request<Conversation>('/conversations/' + encodeURIComponent(id)),
  sendMessage: (id: string, content: string) => request<Message>('/conversations/' + encodeURIComponent(id) + '/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) }),
  uploadFile: (id: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<{ file: FileRecord; task: { id: string; status: string }; run: Run }>('/conversations/' + encodeURIComponent(id) + '/files', { method: 'POST', body })
  },
  logParse: (id: string, file_id: string, feature_field?: string) => request<{ task: { id: string; status: string }; run: Run }>('/conversations/' + encodeURIComponent(id) + '/log-parse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file_id, ...(feature_field ? { feature_field } : {}) }) }),
  fieldMapping: (id: string, input: MappingInput, key: string) => request<{ task: { id: string; status: string }; run: Run }>('/conversations/' + encodeURIComponent(id) + '/field-mapping', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(input) }),
  mappingView: (id: string, query: MappingQuery, signal?: AbortSignal) => {
    const params = new URLSearchParams({ page: String(query.page), q: query.q, status: query.status })
    if (query.sub_rule !== undefined) params.set('sub_rule', query.sub_rule)
    return request<MappingView>('/artifacts/' + encodeURIComponent(id) + '/mapping-view?' + params, { signal })
  },
  mappingDownload,
  submitLogKnowledge: (artifactId: string) => request<{ task: { id: string; status: string }; run: Run }>('/artifacts/' + encodeURIComponent(artifactId) + '/submit-log-knowledge', { method: 'POST' }),
  retryRun: (id: string) => request<Run>('/runs/' + encodeURIComponent(id) + '/retry', { method: 'POST' }),
  cancelToken: (id: string) => request<{ token: string }>('/runs/' + encodeURIComponent(id) + '/cancel-token', { method: 'POST' }),
  cancelRun: (id: string, token: string) => request<Run>('/runs/' + encodeURIComponent(id) + '/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) }),
  run: (id: string) => request<Run>('/runs/' + encodeURIComponent(id)),
  eventsUrl: (id: string, after: number) => base + '/conversations/' + encodeURIComponent(id) + '/events?after=' + after,
}
