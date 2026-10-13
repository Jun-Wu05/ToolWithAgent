export type Identity = { id: string; display_name: string; role: string }
export type ConversationSummary = { id: string; title: string; created_at: string; updated_at: string }
export type Message = { id: string; actor: string; content: string; created_at?: string }
export type FileRecord = { id: string; name: string; size?: number; parse_status?: string; created_at?: string }
export type ClassificationArtifact = {
  id: string
  run_id: string
  file_id: string
  kind: 'log_classification'
  status: string
  summary: { log_types: { name: string; count: number }[]; coverage: { matched_lines: number; total_lines: number }; rule_summary: string }
  submission_eligible: boolean
  submission_status?: string
  application_id?: number
  created_at?: string
}
export type Run = { id: string; task_id?: string; file_id?: string; status: string; kind?: string; type?: string; error_code?: string | null; error_message?: string | null; created_at?: string; updated_at?: string }
export type Conversation = ConversationSummary & { messages: Message[]; files: FileRecord[]; runs: Run[]; artifacts?: ClassificationArtifact[] }
export type EventRecord = { sequence: number; event_type: string; resource_type: string; resource_id: string; payload: Record<string, unknown> }
export type ApiError = Error & { code?: string; status?: number }
const base = '/api/v2'
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(base + path, { credentials: 'include', ...init })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = new Error(body?.error?.message || body?.detail || '请求失败，请稍后重试。') as ApiError
    error.code = body?.error?.code
    error.status = response.status
    throw error
  }
  return response.json() as Promise<T>
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
  submitLogKnowledge: (artifactId: string) => request<{ task: { id: string; status: string }; run: Run }>('/artifacts/' + encodeURIComponent(artifactId) + '/submit-log-knowledge', { method: 'POST' }),
  retryRun: (id: string) => request<Run>('/runs/' + encodeURIComponent(id) + '/retry', { method: 'POST' }),
  cancelToken: (id: string) => request<{ token: string }>('/runs/' + encodeURIComponent(id) + '/cancel-token', { method: 'POST' }),
  cancelRun: (id: string, token: string) => request<Run>('/runs/' + encodeURIComponent(id) + '/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) }),
  run: (id: string) => request<Run>('/runs/' + encodeURIComponent(id)),
  eventsUrl: (id: string, after: number) => base + '/conversations/' + encodeURIComponent(id) + '/events?after=' + after,
}
