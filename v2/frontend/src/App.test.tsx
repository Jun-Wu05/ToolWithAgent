import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { api, saveDownload, type Conversation, type FieldMappingArtifact } from './api'

vi.mock('./api', () => ({
  saveDownload: vi.fn(),
  api: {
    me: vi.fn(), identities: vi.fn(), selectIdentity: vi.fn(), conversations: vi.fn(), createConversation: vi.fn(),
    conversation: vi.fn(), sendMessage: vi.fn(), uploadFile: vi.fn(), logParse: vi.fn(), submitLogKnowledge: vi.fn(), retryRun: vi.fn(), cancelToken: vi.fn(), cancelRun: vi.fn(), run: vi.fn(), eventsUrl: vi.fn(), fieldMapping: vi.fn(), mappingView: vi.fn(), mappingDownload: vi.fn(), createMappingDraft: vi.fn(), mappingDraft: vi.fn(), standardFields: vi.fn(), saveMapping: vi.fn(), confirmMapping: vi.fn(), mappingCandidates: vi.fn(), applyMappingDraft: vi.fn(), discardMappingDraft: vi.fn()
  }
}))
class FakeEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  static instances: FakeEventSource[] = []
  constructor(public url: string) { FakeEventSource.instances.push(this) }
  close() {}
}
const summary = { id: 'conv-1', title: '日志任务', created_at: '2026-09-23T01:00:00Z', updated_at: '2026-09-23T01:00:00Z' }
const detail = { ...summary, messages: [], files: [], runs: [] }
beforeEach(() => {
  vi.stubGlobal('EventSource', FakeEventSource)
  localStorage.clear(); sessionStorage.clear(); FakeEventSource.instances = []
  vi.mocked(api.me).mockResolvedValue({ id: 'u1', display_name: '测试用户', role: 'user' })
  vi.mocked(api.identities).mockResolvedValue({ items: [] })
  vi.mocked(api.conversations).mockResolvedValue({ items: [summary] })
  vi.mocked(api.conversation).mockResolvedValue(detail)
  vi.mocked(api.createConversation).mockResolvedValue(summary)
  vi.mocked(api.sendMessage).mockResolvedValue({ id: 'm1', content: '检查日志', actor: 'user' })
  vi.mocked(api.uploadFile).mockResolvedValue({ file: { id: 'f1', name: 'log.txt' }, task: { id: 't1', status: 'queued' }, run: { id: 'r1', status: 'queued' } })
  vi.mocked(api.logParse).mockResolvedValue({ task: { id: 't2', status: 'queued' }, run: { id: 'r2', status: 'queued' } })
  vi.mocked(api.submitLogKnowledge).mockResolvedValue({ task: { id: 't3', status: 'queued' }, run: { id: 'r3', status: 'queued' } })
  vi.mocked(api.fieldMapping).mockResolvedValue({ task: { id: 'tm1', status: 'queued' }, run: { id: 'rm1', status: 'queued' } })
  vi.mocked(api.mappingView).mockResolvedValue({ artifact_id: 'map-1', sub_rules: [{ id: '0', name: '登录', field_count: 1 }], sub_rule_id: '0', items: [{ source_path: 'src_ip', samples: ['敏感样例'], expanded_samples: [{ value: '敏感样例', line_number: 1 }], standard_field: '源地址', evidence: '名称匹配', status: 'matched', warning: '', user_modified: false }], total: 1, page: 1, page_size: 50, sample_line_reference: 'log_entry' })
  vi.mocked(api.createMappingDraft).mockResolvedValue({ id: 'draft-1', conversation_id: 'conv-1', base_artifact_id: 'map-1', revision: 0, status: 'active', changed_count: 0, operation_count: 0, operations: [], base_current: true, apply_run_id: null, applied_artifact_id: null })
  vi.mocked(api.mappingDraft).mockImplementation(async () => ({ id: 'draft-1', conversation_id: 'conv-1', base_artifact_id: 'map-1', revision: 0, status: 'active', changed_count: 0, operation_count: 0, operations: [], base_current: true, apply_run_id: null, applied_artifact_id: null }))
  vi.mocked(api.standardFields).mockResolvedValue({ items: [] })
  vi.mocked(api.mappingDownload).mockResolvedValue({ name: 'mappedconfig_Base64.txt', blob: new Blob(['payload']) })
  vi.mocked(api.cancelToken).mockResolvedValue({ token: 'cancel-token' })
  vi.mocked(api.cancelRun).mockResolvedValue({ id: 'r2', status: 'cancelled' })
  vi.mocked(api.eventsUrl).mockImplementation((id, after) => '/events/' + id + '?after=' + after)
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })
describe('V2 workbench', () => {
  it('restores the selected conversation and persists the theme', async () => {
    render(<App />)
    expect(await screen.findByRole('heading', { name: '日志任务' })).toBeInTheDocument()
    expect(api.conversation).toHaveBeenCalledWith('conv-1')
    fireEvent.click(screen.getByRole('button', { name: '切换深色主题' }))
    expect(localStorage.getItem('twa-v2-theme')).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
  it('sends text and uploads a file to the current conversation', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    fireEvent.change(screen.getByRole('textbox', { name: '消息内容' }), { target: { value: '检查日志' } })
    fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('conv-1', '检查日志'))
    const input = screen.getByLabelText('选择文件')
    fireEvent.change(input, { target: { files: [new File(['line'], 'log.txt', { type: 'text/plain' })] } })
    await waitFor(() => expect(api.uploadFile).toHaveBeenCalledWith('conv-1', expect.objectContaining({ name: 'log.txt' })))
  })
  it('shows the persisted user author and file validation state', async () => {
    vi.mocked(api.conversation).mockResolvedValue({
      ...detail,
      messages: [{ id: 'm1', actor: 'user', content: '检查日志' }],
      files: [{ id: 'f1', name: 'log.txt', parse_status: 'succeeded' }],
    })
    render(<App />)
    expect(await screen.findByText('你')).toBeInTheDocument()
    expect(screen.getByText('已完成')).toBeInTheDocument()
  })
  it('starts log extraction from a validated file with an explicit feature field', async () => {
    vi.mocked(api.conversation).mockResolvedValue({
      ...detail, files: [{ id: 'f1', name: 'events.log', parse_status: 'succeeded' }]
    })
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    fireEvent.change(screen.getByRole('textbox', { name: 'events.log 分类特征字段' }), { target: { value: 'kind' } })
    fireEvent.click(screen.getByRole('button', { name: '提取日志类型' }))
    await waitFor(() => expect(api.logParse).toHaveBeenCalledWith('conv-1', 'f1', 'kind'))
  })
  it('shows a safe result and submits eligible knowledge explicitly', async () => {
    vi.mocked(api.conversation).mockResolvedValue({
      ...detail,
      artifacts: [{ id: 'a1', run_id: 'r2', file_id: 'f1', kind: 'log_classification', status: 'published',
        summary: { log_types: [{ name: '登录事件', count: 3 }], coverage: { matched_lines: 3, total_lines: 4 }, rule_summary: '按 kind 区分' },
        submission_eligible: true }]
    })
    render(<App />)
    await screen.findByText('登录事件 · 3')
    expect(screen.getByText('覆盖率：3 / 4')).toBeInTheDocument()
    expect(screen.queryByText('raw secret')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '申请加入知识库' }))
    await waitFor(() => expect(api.submitLogKnowledge).toHaveBeenCalledWith('a1'))
  })
  it('hides submission for an ineligible result and confirms stop before cancelling', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.mocked(api.conversation).mockResolvedValue({
      ...detail, runs: [{ id: 'r2', status: 'running', kind: 'log_parse' }],
      artifacts: [{ id: 'a1', run_id: 'r1', file_id: 'f1', kind: 'log_classification', status: 'published',
        summary: { log_types: [], coverage: { matched_lines: 1, total_lines: 3 }, rule_summary: '' },
        submission_eligible: false }]
    })
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    expect(screen.queryByRole('button', { name: '申请加入知识库' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '停止' }))
    await waitFor(() => expect(api.cancelRun).toHaveBeenCalledWith('r2', 'cancel-token'))
  })
  it('does not show user write actions to Developer', async () => {
    vi.mocked(api.me).mockResolvedValue({ id: 'dev', display_name: '开发者', role: 'developer' })
    vi.mocked(api.conversation).mockResolvedValue({
      ...detail, files: [{ id: 'f1', name: 'events.log', parse_status: 'succeeded' }],
      artifacts: [{ id: 'a1', run_id: 'r2', file_id: 'f1', kind: 'log_classification', status: 'published',
        summary: { log_types: [], coverage: { matched_lines: 0, total_lines: 0 }, rule_summary: '' },
        submission_eligible: true }]
    })
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    expect(screen.queryByRole('button', { name: '提取日志类型' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '申请加入知识库' })).not.toBeInTheDocument()
  })
  it('offers retry for a cancelled knowledge submission and calls the retry endpoint', async () => {
    vi.mocked(api.conversation).mockResolvedValue({
      ...detail, runs: [{ id: 'r3', status: 'cancelled', kind: 'log_knowledge_submit' }],
      artifacts: [{ id: 'a1', run_id: 'r2', file_id: 'f1', kind: 'log_classification', status: 'published',
        summary: { log_types: [], coverage: { matched_lines: 3, total_lines: 3 }, rule_summary: '按 kind 区分' },
        submission_eligible: true, submission_status: 'cancelled' }]
    })
    vi.mocked(api.retryRun).mockResolvedValue({ id: 'r4', status: 'queued' })
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    fireEvent.click(screen.getByText('执行详情 ›'))
    expect(screen.getByLabelText('执行详情')).toHaveTextContent('已取消')
    fireEvent.click(screen.getByRole('button', { name: '重新执行' }))
    await waitFor(() => expect(api.retryRun).toHaveBeenCalledWith('r3'))
  })
  it('updates an open run drawer when SSE refreshes its status', async () => {
    vi.mocked(api.conversation)
      .mockResolvedValueOnce({ ...detail, runs: [{ id: 'run-1', status: 'queued' }] })
      .mockResolvedValue({ ...detail, runs: [{ id: 'run-1', status: 'succeeded' }] })
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    fireEvent.click(screen.getByText('执行详情 ›'))
    const drawer = screen.getByLabelText('执行详情')
    expect(drawer).toHaveTextContent('排队中')
    FakeEventSource.instances.at(-1)?.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ sequence: 5 }) }))
    await waitFor(() => expect(drawer).toHaveTextContent('已完成'))
  })
  it('ignores an old SSE refresh after switching conversations', async () => {
    const second = { ...summary, id: 'conv-2', title: '第二会话' }
    vi.mocked(api.conversations).mockResolvedValue({ items: [summary, second] })
    let resolveOld: (value: typeof detail) => void = () => {}
    const oldRefresh = new Promise<typeof detail>(resolve => { resolveOld = resolve })
    let first = true
    vi.mocked(api.conversation).mockImplementation(id => {
      if (id === 'conv-2') return Promise.resolve({ ...detail, ...second })
      if (first) { first = false; return Promise.resolve(detail) }
      return oldRefresh
    })
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    FakeEventSource.instances.at(-1)?.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ sequence: 6 }) }))
    fireEvent.click(screen.getByRole('button', { name: /第二会话/ }))
    await screen.findByRole('heading', { name: '第二会话' })
    await act(async () => resolveOld({ ...detail, title: '旧会话秘密' }))
    expect(screen.getByRole('heading', { name: '第二会话' })).toBeInTheDocument()
    expect(screen.queryByText('旧会话秘密')).not.toBeInTheDocument()
  })
  it('refreshes persisted detail after an SSE message', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    const before = vi.mocked(api.conversation).mock.calls.length
    FakeEventSource.instances.at(-1)?.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ sequence: 4 }) }))
    await waitFor(() => expect(api.conversation).toHaveBeenCalledTimes(before + 1))
  })
  it('keeps the newest run state when same-view SSE refreshes finish out of order', async () => {
    const queued = { ...detail, runs: [{ id: 'run-1', status: 'queued' }] }
    const completed = { ...detail, runs: [{ id: 'run-1', status: 'succeeded' }] }
    let resolveOld: (value: typeof queued) => void = () => {}
    let resolveNew: (value: typeof completed) => void = () => {}
    const oldRefresh = new Promise<typeof queued>(resolve => { resolveOld = resolve })
    const newRefresh = new Promise<typeof completed>(resolve => { resolveNew = resolve })
    vi.mocked(api.conversation)
      .mockResolvedValueOnce(queued)
      .mockImplementationOnce(() => oldRefresh)
      .mockImplementationOnce(() => newRefresh)
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    fireEvent.click(screen.getByText('执行详情 ›'))
    const drawer = screen.getByLabelText('执行详情')
    const source = FakeEventSource.instances.at(-1)
    source?.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ sequence: 7 }) }))
    source?.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ sequence: 8 }) }))
    await waitFor(() => expect(api.conversation).toHaveBeenCalledTimes(3))
    await act(async () => resolveNew(completed))
    await waitFor(() => expect(drawer).toHaveTextContent('已完成'))
    await act(async () => resolveOld(queued))
    expect(drawer).toHaveTextContent('已完成')
  })
})


describe('field mapping workflow', () => {
  it('requires product and vendor, preserves values on error and submits the explicit file', async () => {
    vi.mocked(api.conversation).mockResolvedValue({ ...detail, files: [{ id: 'f1', name: 'input.b64', mapping_eligible: true }] })
    vi.mocked(api.fieldMapping).mockRejectedValue(new Error('主数据已变化，请重新选择输入。'))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '标准字段映射' }))
    const start = screen.getByRole('button', { name: '开始映射' })
    expect(start).toBeDisabled()
    fireEvent.change(screen.getByRole('textbox', { name: '产品' }), { target: { value: '测试产品' } })
    fireEvent.change(screen.getByRole('textbox', { name: '厂商' }), { target: { value: '测试厂商' } })
    fireEvent.click(start)
    await screen.findByText('主数据已变化，请重新选择输入。')
    expect(screen.getByRole('textbox', { name: '产品' })).toHaveValue('测试产品')
    expect(api.fieldMapping).toHaveBeenCalledWith('conv-1', { file_id: 'f1', product: '测试产品', log_vendor: '测试厂商' }, expect.any(String))
  })
  it.each(['developer', 'admin'])('hides mapping writes from %s and from ineligible inputs', async role => {
    vi.mocked(api.me).mockResolvedValue({ id: 'observer', display_name: '只读身份', role })
    vi.mocked(api.conversation).mockResolvedValue({ ...detail, files: [{ id: 'f1', name: 'input.log', mapping_eligible: true }] })
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    expect(screen.queryByRole('button', { name: '标准字段映射' })).not.toBeInTheDocument()
  })
})


const mappedArtifact: FieldMappingArtifact = { id: 'map-1', run_id: 'rm1', file_id: 'f1', kind: 'field_mapping', status: 'published', current: true,
  summary: { rule_count: 1, field_count: 1, matched_count: 1, unmatched_count: 0, parse_error_count: 0 } }
const mappingDetail: Conversation = { ...detail, artifacts: [mappedArtifact] }
const fillSource = () => {
  fireEvent.change(screen.getByRole('textbox', { name: '产品' }), { target: { value: '测试产品' } })
  fireEvent.change(screen.getByRole('textbox', { name: '厂商' }), { target: { value: '测试厂商' } })
}

describe('mapping integration boundaries', () => {
  it('submits the eligible classification, retains an idempotency key on retry and shows queue state', async () => {
    const classified: Conversation = { ...detail, artifacts: [{ id: 'class-1', kind: 'log_classification', run_id: 'rc1', file_id: 'f1', status: 'published', mapping_eligible: true, submission_eligible: false,
      summary: { log_types: [], coverage: { matched_lines: 2, total_lines: 2 }, rule_summary: '分类完成' } }] }
    vi.mocked(api.conversation).mockResolvedValueOnce(classified).mockResolvedValue({ ...classified, runs: [{ id: 'rm1', status: 'queued', kind: 'field_mapping' }] })
    vi.mocked(api.fieldMapping).mockRejectedValueOnce(new Error('网络连接中断')).mockResolvedValue({ task: { id: 'tm1', status: 'queued' }, run: { id: 'rm1', status: 'queued' } })
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '标准字段映射' }))
    fillSource()
    fireEvent.change(screen.getByRole('textbox', { name: '数据源（可选）' }), { target: { value: '测试数据源' } })
    fireEvent.click(screen.getByRole('button', { name: '开始映射' }))
    await screen.findByText('网络连接中断')
    fireEvent.click(screen.getByRole('button', { name: '开始映射' }))
    await screen.findByText('标准字段映射已排队。')
    await screen.findByText('标准字段映射排队中')
    const calls = vi.mocked(api.fieldMapping).mock.calls
    expect(calls[0][1]).toEqual({ classification_artifact_id: 'class-1', product: '测试产品', log_vendor: '测试厂商', data_source: '测试数据源' })
    expect(calls[1][2]).toBe(calls[0][2])
    expect(screen.queryByRole('textbox', { name: '产品' })).not.toBeInTheDocument()
  })
  it('honors server eligibility rather than filename or file validation heuristics', async () => {
    vi.mocked(api.conversation).mockResolvedValue({ ...detail, files: [{ id: 'old', name: 'old.log', parse_status: 'succeeded', mapping_eligible: false }, { id: 'pending', name: 'new.log', parse_status: 'queued', mapping_eligible: false }] })
    render(<App />)
    await screen.findByRole('heading', { name: '日志任务' })
    expect(screen.queryByRole('button', { name: '标准字段映射' })).not.toBeInTheDocument()
  })
  it('enlarges only the middle region, keeps composer/theme/navigation and returns focus to the card', async () => {
    vi.mocked(api.conversation).mockResolvedValue({ ...mappingDetail, runs: [{ id: 'rm1', status: 'running', kind: 'field_mapping' }] })
    render(<App />)
    const open = await screen.findByRole('button', { name: '查看结果' })
    expect(screen.queryByText('敏感样例')).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: '消息内容' }), { target: { value: '尚未发送的内容' } })
    fireEvent.click(screen.getByRole('button', { name: '切换深色主题' }))
    fireEvent.click(open)
    await screen.findByText('src_ip')
    expect(screen.getByRole('navigation', { name: '主导航' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('尚未发送的内容')
    expect(document.documentElement.dataset.theme).toBe('dark')
    fireEvent.click(screen.getByRole('button', { name: '查看执行详情' }))
    expect(screen.getAllByLabelText('执行详情')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: '关闭执行详情' }))
    fireEvent.click(screen.getByRole('button', { name: '返回对话' }))
    const returned = await screen.findByRole('button', { name: '查看结果' })
    expect(returned).toHaveFocus()
    expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('尚未发送的内容')
  })
  it('keeps stale artifacts readable and downloadable while showing their status', async () => {
    vi.mocked(api.conversation).mockResolvedValue({ ...detail, artifacts: [{ ...mappedArtifact, status: 'stale', current: false }] })
    render(<App />)
    await screen.findByText('结果已过期，可查看和下载历史配置。')
    fireEvent.click(screen.getByRole('button', { name: '下载配置' }))
    await waitFor(() => expect(saveDownload).toHaveBeenCalledWith(expect.objectContaining({ name: 'mappedconfig_Base64.txt' })))
    fireEvent.click(screen.getByRole('button', { name: '查看结果' }))
    await screen.findByText('src_ip')
    expect(screen.getByText(/结果已过期，保留用于查看和下载/)).toBeInTheDocument()
  })
  it('does not restore the old result or samples after switching conversations', async () => {
    const second = { ...summary, id: 'conv-2', title: '第二会话' }
    vi.mocked(api.conversations).mockResolvedValue({ items: [summary, second] })
    vi.mocked(api.conversation).mockImplementation(id => Promise.resolve(id === 'conv-1' ? mappingDetail : { ...detail, ...second }))
    let resolveOld: (view: Awaited<ReturnType<typeof api.mappingView>>) => void = () => {}
    vi.mocked(api.mappingView).mockImplementation(() => new Promise(resolve => { resolveOld = resolve }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '查看结果' }))
    fireEvent.click(screen.getByRole('button', { name: /第二会话/ }))
    await screen.findByRole('heading', { name: '第二会话' })
    await act(async () => resolveOld({ artifact_id: 'map-1', sub_rules: [], sub_rule_id: '', items: [], total: 0, page: 1, page_size: 50, sample_line_reference: 'log_entry' }))
    expect(screen.queryByLabelText('字段映射结果')).not.toBeInTheDocument()
    expect(screen.queryByText('敏感样例')).not.toBeInTheDocument()
  })
  it('does not show a late mapping submission feedback after switching identity', async () => {
    const second = { ...summary, id: 'conv-2', title: '另一身份会话' }
    const user = { id: 'u1', display_name: '测试用户', role: 'user' }
    const other = { id: 'u2', display_name: '另一用户', role: 'user' }
    let selected = false
    vi.mocked(api.identities).mockResolvedValue({ items: [user, other] })
    vi.mocked(api.me).mockImplementation(() => Promise.resolve(selected ? other : user))
    vi.mocked(api.conversations).mockImplementation(() => Promise.resolve({ items: [selected ? second : summary] }))
    vi.mocked(api.conversation).mockImplementation(id => Promise.resolve(id === 'conv-1' ? { ...detail, files: [{ id: 'f1', name: 'events.log', mapping_eligible: true }] } : { ...detail, ...second }))
    vi.mocked(api.selectIdentity).mockImplementation(() => { selected = true; return Promise.resolve(other) })
    let resolveOld: (result: Awaited<ReturnType<typeof api.fieldMapping>>) => void = () => {}
    vi.mocked(api.fieldMapping).mockImplementation(() => new Promise(resolve => { resolveOld = resolve }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '标准字段映射' }))
    fillSource()
    fireEvent.click(screen.getByRole('button', { name: '开始映射' }))
    fireEvent.change(screen.getByLabelText('开发身份切换'), { target: { value: 'u2' } })
    await screen.findByRole('heading', { name: '另一身份会话' })
    await act(async () => resolveOld({ task: { id: 'old-task', status: 'queued' }, run: { id: 'old-run', status: 'queued' } }))
    expect(screen.queryByText('标准字段映射已排队。')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '产品' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '另一身份会话' })).toBeInTheDocument()
  })
  it('discards a download completed after leaving the conversation', async () => {
    const second = { ...summary, id: 'conv-2', title: '第二会话' }
    vi.mocked(api.conversations).mockResolvedValue({ items: [summary, second] })
    vi.mocked(api.conversation).mockImplementation(id => Promise.resolve(id === 'conv-1' ? mappingDetail : { ...detail, ...second }))
    let resolveOld: (result: Awaited<ReturnType<typeof api.mappingDownload>>) => void = () => {}
    vi.mocked(api.mappingDownload).mockImplementation(() => new Promise(resolve => { resolveOld = resolve }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '下载配置' }))
    fireEvent.click(screen.getByRole('button', { name: /第二会话/ }))
    await screen.findByRole('heading', { name: '第二会话' })
    await act(async () => resolveOld({ name: 'old_Base64.txt', blob: new Blob(['secret']) }))
    expect(saveDownload).not.toHaveBeenCalled()
  })
})


describe('mapping view identity fence', () => {
  it('discards a private result response after switching identity', async () => {
    const user = { id: 'u1', display_name: '测试用户', role: 'user' }
    const other = { id: 'dev', display_name: '开发者', role: 'developer' }
    const second = { ...summary, id: 'conv-2', title: '另一身份会话' }
    let selected = false
    vi.mocked(api.identities).mockResolvedValue({ items: [user, other] })
    vi.mocked(api.me).mockImplementation(() => Promise.resolve(selected ? other : user))
    vi.mocked(api.conversations).mockImplementation(() => Promise.resolve({ items: [selected ? second : summary] }))
    vi.mocked(api.conversation).mockImplementation(id => Promise.resolve(id === 'conv-1' ? mappingDetail : { ...detail, ...second }))
    vi.mocked(api.selectIdentity).mockImplementation(() => { selected = true; return Promise.resolve(other) })
    let resolveOld: (result: Awaited<ReturnType<typeof api.mappingView>>) => void = () => {}
    vi.mocked(api.mappingView).mockImplementation(() => new Promise(resolve => { resolveOld = resolve }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '查看结果' }))
    await screen.findByText('正在加载字段…')
    fireEvent.change(screen.getByLabelText('开发身份切换'), { target: { value: 'dev' } })
    await screen.findByRole('heading', { name: '另一身份会话' })
    await act(async () => resolveOld({ artifact_id: 'map-1', sub_rules: [], sub_rule_id: '', items: [{ source_path: '旧身份秘密', samples: ['敏感样例'], expanded_samples: [], standard_field: '', evidence: '', status: 'unmatched', warning: '', user_modified: false }], total: 1, page: 1, page_size: 50, sample_line_reference: 'log_entry', event_annotations: [{ rule_name: '旧标注子规则', event_name: '旧身份事件名称', event_level: 'unknown', threat_source_field: '旧身份来源', threat_types: [], status: 'uncertain' }], warnings: [{ code: 'threat_chain_warning', message: '⚠️ 旧身份私有警告' }] }))
    expect(screen.queryByText('旧身份事件名称')).not.toBeInTheDocument()
    expect(screen.queryByText('旧身份来源')).not.toBeInTheDocument()
    expect(screen.queryByText('⚠️ 旧身份私有警告')).not.toBeInTheDocument()
    expect(screen.queryByText('旧身份秘密')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('字段映射结果')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '标准字段映射' })).not.toBeInTheDocument()
  })
  it('discards a late submit error after switching conversation', async () => {
    const second = { ...summary, id: 'conv-2', title: '第二会话' }
    vi.mocked(api.conversations).mockResolvedValue({ items: [summary, second] })
    vi.mocked(api.conversation).mockImplementation(id => Promise.resolve(id === 'conv-1' ? { ...detail, files: [{ id: 'f1', name: 'events.log', mapping_eligible: true }] } : { ...detail, ...second }))
    let rejectOld: (error: Error) => void = () => {}
    vi.mocked(api.fieldMapping).mockImplementation(() => new Promise((_, reject) => { rejectOld = reject }))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '标准字段映射' }))
    fillSource()
    fireEvent.click(screen.getByRole('button', { name: '开始映射' }))
    fireEvent.click(screen.getByRole('button', { name: /第二会话/ }))
    await screen.findByRole('heading', { name: '第二会话' })
    await act(async () => rejectOld(new Error('旧会话错误')))
    expect(screen.queryByText('旧会话错误')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '产品' })).not.toBeInTheDocument()
  })
})


describe('mapping safe summary', () => {
  it('keeps annotation values and warning text out of the summary until the protected result is opened', async () => {
    vi.mocked(api.conversation).mockResolvedValue({ ...detail, artifacts: [{ ...mappedArtifact, summary: { ...mappedArtifact.summary, uncertain_annotation_count: 1, warning_codes: ['threat_chain_warning'] } }] })
    vi.mocked(api.mappingView).mockResolvedValue({ artifact_id: 'map-1', sub_rules: [{ id: '0', name: '子规则', field_count: 0 }], sub_rule_id: '0', items: [], total: 0, page: 1, page_size: 50, sample_line_reference: 'log_entry',
      event_annotations: [{ rule_name: '私人子规则', event_name: '私人事件名称', event_level: 'unknown', threat_source_field: '私人来源字段', threat_types: [], status: 'uncertain' }],
      warnings: [{ code: 'threat_chain_warning', message: '⚠️ 私人业务警告：威胁类型未生成。' }] })
    render(<App />)
    await screen.findByText('待人工确认：1 条事件名称标注。')
    expect(screen.getByText('威胁类型处理有提醒，请查看结果。')).toBeInTheDocument()
    expect(api.mappingView).not.toHaveBeenCalled()
    expect(screen.queryByText('私人事件名称')).not.toBeInTheDocument()
    expect(screen.queryByText('私人来源字段')).not.toBeInTheDocument()
    expect(screen.queryByText('⚠️ 私人业务警告：威胁类型未生成。')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看结果' }))
    await screen.findByText('私人事件名称')
    expect(screen.getByRole('table', { name: '事件名称标注' })).toHaveTextContent('私人来源字段')
    expect(screen.getByText('⚠️ 私人业务警告：威胁类型未生成。')).toBeInTheDocument()
  })
})
