import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { api } from './api'

vi.mock('./api', () => ({
  api: {
    me: vi.fn(), identities: vi.fn(), conversations: vi.fn(), createConversation: vi.fn(),
    conversation: vi.fn(), sendMessage: vi.fn(), uploadFile: vi.fn(), logParse: vi.fn(), submitLogKnowledge: vi.fn(), retryRun: vi.fn(), cancelToken: vi.fn(), cancelRun: vi.fn(), run: vi.fn(), eventsUrl: vi.fn()
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
