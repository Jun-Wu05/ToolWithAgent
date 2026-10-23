export type Identity = { id: string; display_name: string; role: string }
export type ConversationSummary = { id: string; title: string; created_at: string; updated_at: string }
export type Message = { id: string; actor: string; content: string; created_at?: string; run_id?: string | null }
export type FileRecord = { id: string; name: string; size?: number; role?: 'primary' | 'enum_mapping'; active?: boolean; parse_status?: string; mapping_eligible?: boolean; created_at?: string }
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
  source_artifact_id?: string; created_at?: string; config_ref?: string; message_id?: string | null; result_message_id?: string | null
  summary: { rule_count: number; field_count: number; matched_count: number; unmatched_count: number; parse_error_count: number; uncertain_annotation_count?: number; warning_codes?: MappingWarning['code'][] }
}
export type MappingInput = { file_id?: string; classification_artifact_id?: string; product: string; log_vendor: string; data_source?: string }
export type MappingStatus = 'matched' | 'unmatched' | 'parse_error'
export type MappingProposal = { sub_rule_id: string; source_path: string; standard_field: string | null; linked_sub_rule_ids: string[] }
export type MappingCandidates = { source_path: string; standard_field: string | null; items: { sub_rule_id: string; name: string; current_standard_field: string; samples: string[]; selectable: boolean; conflict_source_path: string | null; selected: boolean; disabled_reason?: string | null }[] }
export type MappingDraftSummary = { id: string; conversation_id: string; base_artifact_id: string; revision: number; status: 'active' | 'applying' | 'applied' | 'discarded'; changed_count: number; apply_run_id: string | null; applied_artifact_id: string | null; base_current: boolean }
export type MappingDraft = MappingDraftSummary & { operation_count: number; operations: { operation_key: string; proposal: MappingProposal; changes: Omit<MappingProposal, 'linked_sub_rule_ids'>[] }[] }
export type StandardField = { name: string; category: string; occupied_by: string | null; disabled_reason: string | null }
export type MappingConflict = { operation_key: string; proposal: MappingProposal; occupied_by: string; candidates: MappingCandidates }
export type DraftSave = { draft: MappingDraft; candidates: MappingCandidates }
export type MappingView = {
  artifact_id: string; sub_rules: { id: string; name: string; field_count: number }[]; sub_rule_id: string
  items: { source_path: string; samples: string[]; expanded_samples: { value: string; line_number: number | null; source?: string }[];
    standard_field: string; evidence: string; status: MappingStatus; warning: string; user_modified: boolean; sub_rule_id?: string; operation_key?: string; draft_modified?: boolean; group_status?: MappingStatus; editable?: boolean; disabled_reason?: string | null }[]
  total: number; page: number; page_size: number; sample_line_reference: 'log_entry'
  event_annotations?: EventAnnotation[]; warnings?: MappingWarning[]
}
export type MappingQuery = { sub_rule?: string; page: number; q: string; status: string; draft_id?: string }
export type ArtifactDownload = { name: string; blob: Blob }
export type AdminOverview = { runs: Record<string, number>; users: number; conversations: number; worker: { lease_owner: string | null; lease_expires_at: string | null; epoch: number } }
export type AdminRun = { id: string; task_id: string; kind: string; message_id?: string | null; file_id?: string | null; status: string; attempt: number; queued_at: string; started_at: string | null; finished_at: string | null; error_code?: string | null; created_at: string; updated_at: string; owner_id: string; owner_name: string; conversation_id: string; conversation_title: string }
export type AdminRunPage = { items: AdminRun[]; total: number; page: number; page_size: number }
export type AdminAuditEvent = { id: string; action: string; target_type: string; target_id: string; created_at: string; reason: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; actor_name: string }
export type AdminAuditPage = { items: AdminAuditEvent[]; total: number; page: number; page_size: number }
export type ProgressSummary = {phase?: string; progress_status?: string; operation?: string; dependency_scope_ids?: string[]}
export type RunEvent = {sequence: number; scope_type: string; scope_id: string; event_type: string; status: string; summary?: ProgressSummary; created_at?: string}
export type Run = { id: string; task_id?: string; file_id?: string; status: string; kind?: string; type?: string; error_code?: string | null; error_message?: string | null; created_at?: string; updated_at?: string; message_id?: string | null; events?: RunEvent[] }
export type FieldChangeSummary = { run_id: string; revision: number; status: string; apply_run_id: string | null; applied_artifact_id: string | null; undo_run_id: string | null; restored_artifact_id: string | null }
export type FieldChangePreview = FieldChangeSummary & { task_id: string; current: boolean; selected_group_ids: string[]; groups: { id: string; fields: string[]; deletes: string[]; status: string; changes: { sub_rule_id: string; sub_rule_name: string; field: string; kind: 'add' | 'modify' | 'delete'; before: unknown; after: unknown }[] }[] }
export type FieldDeleteConfirmation = { token: string; checkpoint_revision: number; payload: { deletes: string[]; downstream: { id: string; kind: string; version: number }[] } }
export type Conversation = ConversationSummary & { messages: Message[]; files: FileRecord[]; runs: Run[]; artifacts?: Artifact[]; drafts?: MappingDraftSummary[]; field_changes?: FieldChangeSummary[]; session_facts?: SessionFacts | null; session_facts_error?: string | null }
export type BusinessArtifact = { id: string; run_id: string; kind: 'enum_values' | 'threat_mapping' | 'config_export'; status: string; current: boolean; item_count?: number; source_field?: string; summary?: Record<string, unknown>; message_id?: string | null; result_message_id?: string | null; created_at?: string }
export type Artifact = ClassificationArtifact | FieldMappingArtifact | BusinessArtifact
export type SessionFacts = { has_logs?: boolean; has_decoded_config?: boolean; has_log_classification?: boolean; available_config_refs: string[]; enum_mapping_target_fields: string[]; referenceable_artifacts: { source_ref: string; artifact_type: string; source_field: string | null; item_count: number; target_bindings: {config_ref: string; target_field: string}[] }[] }
export type OperationInput = { step: { step_id: 'operation'; type: 'enum_extract' | 'threat_mapping' | 'fill' | 'remove_mapping' | 'export'; source_ref?: string; config_ref?: string; target_field?: string; target_fields?: string[]; fill_kind?: 'enum' | 'threat'; values?: string[] }; source_artifact_id?: string; config_artifact_id?: string }
export type Confirmation = { token: string; checkpoint_revision: number; kind: string; payload: { question: string; reason_code?: string; choices?: string[]; operations?: unknown[] } }
export type EventRecord = { sequence: number; event_type: string; resource_type: string; resource_id: string; payload: Record<string, unknown> }
export type ApiError = Error & { code?: string; status?: number; details?: unknown }
const base = '/api/v2'
const messages: Record<string, string> = {
  field_preview_resolution_required: '有未处理的字段变更，请先查看变更并应用或取消。',
  field_revision_conflict: '变更选择已在其他页面更新，请重新加载。',
  field_preview_not_editable: '当前变更不能继续编辑，请检查执行状态。',
  field_undo_stale: '当前版本已变化，不能撤销这次提交；请查看最新结果。',
  business_input_stale: '输入或配置已变化，请取消旧变更并重新发起。',
  confirmation_resolution_required: '有待确认的执行方案，请先确认或取消。',
  continuation_stale: '执行输入已变化，请取消旧方案后重新发起。',
  artifact_source_stale: '来源结果已过期，请选择当前结果。',
  config_source_stale: '配置已变化，请选择当前配置。',
  enum_refill_required: '枚举附件已更新，请重新填充后导出。',
  mapping_draft_not_found: '草稿不存在或当前身份无权查看，请返回会话。',
  mapping_draft_empty: '草稿没有实际修改，无需应用。',
  mapping_source_not_editable: '该字段由平台维护，不能在此修改。',
  mapping_occupant_not_editable: '目标由平台维护的字段占用，不能替换。',
  mapping_target_invalid: '请选择标准字段目录中的合法中文名称。',
  mapping_scope_invalid: '联动范围无效，请重新选择子规则。',
  mapping_operation_key_invalid: '字段来源已变化，请重新加载草稿。',
  draft_revision_required: '保存需要当前草稿版本，请重新加载草稿。',
  invalid_draft_revision: '草稿版本无效，请重新加载草稿。',
  invalid_request: '提交内容无效，请检查后重试。',
  draft_revision_conflict: '草稿已在其他页面更新，已停止保存。请重新加载草稿。',
  mapping_target_conflict: '这个标准字段已被占用，请确认是否替换。',
  mapping_link_conflict: '所选联动子规则存在占用冲突，请重新选择范围。',
  mapping_base_stale: '草稿来源已过期，可查看或丢弃，请编辑当前正式结果。',
  mapping_catalog_changed: '标准字段目录已变化，请重新加载后检查修改。',
  draft_apply_in_progress: '修改正在应用，请等待执行完成。',
  draft_not_editable: '这份草稿不能继续编辑，请重新打开当前结果。',
  draft_resolution_required: '还有未应用的修改，请先选择如何处理草稿。',
  mapping_draft_apply_stale: '应用时草稿或来源已变化，修改未发布，请重新检查草稿。',
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
  run_not_queued: '该执行已不在排队中，请刷新列表后重试。',
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
    error.details = body?.error?.details
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
  sendMessage: (id: string, content: string, key?: string) => request<Message & {task?: {id: string; status: string}; run?: Run}>('/conversations/' + encodeURIComponent(id) + '/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }), ...(key ? {headers: {'Content-Type': 'application/json', 'Idempotency-Key': key}} : {}) }),
  uploadFile: (id: string, file: File, role?: 'primary' | 'enum_mapping') => {
    const body = new FormData()
    body.append('file', file)
    body.append('role', role || 'primary')
    return request<{ file: FileRecord; task: { id: string; status: string }; run: Run }>('/conversations/' + encodeURIComponent(id) + '/files', { method: 'POST', body })
  },
  logParse: (id: string, file_id: string, feature_field?: string) => request<{ task: { id: string; status: string }; run: Run }>('/conversations/' + encodeURIComponent(id) + '/log-parse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file_id, ...(feature_field ? { feature_field } : {}) }) }),
  fieldMapping: (id: string, input: MappingInput, key: string) => request<{ task: { id: string; status: string }; run: Run }>('/conversations/' + encodeURIComponent(id) + '/field-mapping', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key }, body: JSON.stringify(input) }),
  mappingView: (id: string, query: MappingQuery, signal?: AbortSignal) => {
    const params = new URLSearchParams({ page: String(query.page), q: query.q, status: query.status })
    if (query.sub_rule !== undefined) params.set('sub_rule', query.sub_rule)
    if (query.draft_id) params.set('draft_id', query.draft_id)
    return request<MappingView>('/artifacts/' + encodeURIComponent(id) + '/mapping-view?' + params, { signal })
  },
  mappingDownload,
  cancelFields: (id: string, revision: number, key: string) => request('/runs/' + encodeURIComponent(id) + '/field-change-cancel', {method: 'POST', headers: {'If-Match': String(revision), 'Idempotency-Key': key}}),
  fieldPreview: (id: string) => request<FieldChangePreview>('/runs/' + encodeURIComponent(id) + '/field-change-preview'),
  selectFields: (id: string, revision: number, selected: string[], key: string) => request<FieldChangePreview>('/runs/' + encodeURIComponent(id) + '/field-change-selection', {method: 'POST', headers: {'Content-Type': 'application/json', 'If-Match': String(revision), 'Idempotency-Key': key}, body: JSON.stringify({selected_group_ids: selected})}),
  confirmFieldDeletion: (task: string, revision: number, key: string) => request<FieldDeleteConfirmation>('/tasks/' + encodeURIComponent(task) + '/confirmations', {method: 'POST', headers: {'If-Match': String(revision), 'Idempotency-Key': key}}),
  applyFields: (id: string, revision: number, key: string, token?: string) => request<{run: Run}>('/runs/' + encodeURIComponent(id) + '/field-change-apply', {method: 'POST', headers: {'Content-Type': 'application/json', 'If-Match': String(revision), 'Idempotency-Key': key}, body: JSON.stringify({token})}),
  undoFields: (id: string, key: string) => request<{run: Run}>('/artifacts/' + encodeURIComponent(id) + '/undo', {method: 'POST', headers: {'Idempotency-Key': key}}),
  artifactContent: (id: string) => request<Record<string, unknown>>('/artifacts/' + encodeURIComponent(id) + '/content'),
  operation: (id: string, input: OperationInput, key: string) => request<{task: {id: string; status: string}; run: Run}>('/conversations/' + encodeURIComponent(id) + '/operations', {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': key}, body: JSON.stringify(input)}),
  confirmationToken: (id: string) => request<Confirmation>('/runs/' + encodeURIComponent(id) + '/confirmation-token', {method: 'POST'}),
  confirmRun: (id: string, confirmation: Confirmation, key: string) => request<Run>('/runs/' + encodeURIComponent(id) + '/confirm', {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': key}, body: JSON.stringify({token: confirmation.token, checkpoint_revision: confirmation.checkpoint_revision})}),
  createMappingDraft: (id: string) => request<MappingDraft>('/artifacts/' + encodeURIComponent(id) + '/mapping-drafts', { method: 'POST' }),
  mappingDraft: (id: string) => request<MappingDraft>('/mapping-drafts/' + encodeURIComponent(id)),
  standardFields: (draftId: string, subRule: string, signal?: AbortSignal) => request<{ items: StandardField[] }>('/standard-fields?' + new URLSearchParams({ draft_id: draftId, sub_rule: subRule }), { signal }),
  saveMapping: (id: string, revision: number, operationKey: string, proposal: MappingProposal) => request<DraftSave>('/mapping-drafts/' + encodeURIComponent(id) + '/operations/' + encodeURIComponent(operationKey), { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'If-Match': String(revision) }, body: JSON.stringify(proposal) }),
  mappingCandidates: (id: string, operationKey: string) => request<MappingCandidates>('/mapping-drafts/' + encodeURIComponent(id) + '/same-source-candidates/' + encodeURIComponent(operationKey)),
  confirmMapping: (id: string, revision: number, conflict: MappingConflict, proposal: MappingProposal, confirm: boolean, key: string) => request<DraftSave>('/mapping-drafts/' + encodeURIComponent(id) + '/replacement-confirmations', { method: 'POST', headers: { 'Content-Type': 'application/json', 'If-Match': String(revision), 'Idempotency-Key': key }, body: JSON.stringify({ operation_key: conflict.operation_key, proposal, confirm }) }),
  applyMappingDraft: (id: string, revision: number, key: string) => request<{ task: { id: string; status: string }; run: Run; draft: MappingDraft }>('/mapping-drafts/' + encodeURIComponent(id) + '/apply', { method: 'POST', headers: { 'If-Match': String(revision), 'Idempotency-Key': key } }),
  discardMappingDraft: (id: string, revision: number) => request<MappingDraft>('/mapping-drafts/' + encodeURIComponent(id), { method: 'DELETE', headers: { 'If-Match': String(revision) } }),
  submitLogKnowledge: (artifactId: string) => request<{ task: { id: string; status: string }; run: Run }>('/artifacts/' + encodeURIComponent(artifactId) + '/submit-log-knowledge', { method: 'POST' }),
  retryRun: (id: string) => request<Run>('/runs/' + encodeURIComponent(id) + '/retry', { method: 'POST' }),
  adminOverview: () => request<AdminOverview>('/admin/overview'),
  adminRuns: (status: string, page: number) => request<AdminRunPage>('/admin/runs?' + new URLSearchParams({ ...(status ? { status } : {}), page: String(page) })),
  adminCancelRun: (id: string, reason?: string) => request<{ id: string; status: string; error_code: string }>('/admin/runs/' + encodeURIComponent(id) + '/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: reason || null }) }),
  adminForceStop: (id: string, reason: string) => request<{ id: string; status: string; error_code: string }>('/admin/runs/' + encodeURIComponent(id) + '/force-stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }) }),
  adminAuditEvents: (page: number) => request<AdminAuditPage>('/admin/audit-events?page=' + page),
  cancelToken: (id: string) => request<{ token: string }>('/runs/' + encodeURIComponent(id) + '/cancel-token', { method: 'POST' }),
  cancelRun: (id: string, token: string) => request<Run>('/runs/' + encodeURIComponent(id) + '/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) }),
  run: async (id: string): Promise<Run> => { const run = await request<Run>('/runs/' + encodeURIComponent(id)); return { ...run, error_message: messages[run.error_code || run.error_message || ''] || run.error_message } },
  eventsUrl: (id: string, after: number) => base + '/conversations/' + encodeURIComponent(id) + '/events?after=' + after,
}
