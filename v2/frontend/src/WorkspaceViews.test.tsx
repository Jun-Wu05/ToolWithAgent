import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { compareSnapshots, ExecutionTrace, ResultsWorkspace, TaskOverview } from './WorkspaceViews'
import { api, type Artifact, type Conversation } from './api'

vi.mock('./api', () => ({ api: { artifactContent: vi.fn(), run: vi.fn() } }))
const artifact = (id: string, current = true): Artifact => ({ id, kind: 'field_mapping', run_id: 'run-' + id, file_id: 'file', status: 'published', current, created_at: '2026-10-22T01:00:00Z', summary: { rule_count: 1, field_count: 2, matched_count: 1, unmatched_count: 1, parse_error_count: 0 } })
const versions = [artifact('old-snapshot', false), artifact('current-snapshot')]
const props = { artifacts: versions, active: true, mappingId: 'current-snapshot', mapping: <input aria-label="当前字段筛选" defaultValue="src_ip" />, targetId: null, blocked: false, onMapping: vi.fn(), onOpen: vi.fn(), onDownload: vi.fn() }
beforeEach(() => { vi.mocked(api.artifactContent).mockImplementation(async id => id === 'old-snapshot' ? { config: { field: '旧值', deleted: true }, download_content: 'old-base64' } : { config: { field: '新值', added: true }, download_content: 'new-base64' }) })
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('compares real JSON values and escapes ambiguous paths', () => {
  const result = compareSnapshots({ 'a/b': null, 'a~b': 1, removed: true }, { 'a/b': null, 'a~b': '1', added: [] })
  expect(result).toEqual(expect.arrayContaining([
    { path: '/a~1b', before: 'null', after: 'null', kind: '未变化' },
    { path: '/a~0b', before: '1', after: '"1"', kind: '修改' },
    { path: '/removed', before: 'true', after: undefined, kind: '删除' },
    { path: '/added', before: undefined, after: '[]', kind: '新增' },
  ]))
})

it('compares only actual snapshot IDs and retains the mapping workspace', async () => {
  render(<ResultsWorkspace {...props} />)
  fireEvent.change(screen.getByRole('textbox', { name: '当前字段筛选' }), { target: { value: 'device' } })
  fireEvent.click(screen.getByRole('button', { name: '比较真实版本' }))
  await screen.findByText('/config/field')
  expect(api.artifactContent).toHaveBeenCalledWith('old-snapshot')
  expect(api.artifactContent).toHaveBeenCalledWith('current-snapshot')
  expect(screen.getByText('新增')).toBeVisible()
  expect(screen.getByText('删除')).toBeVisible()
  expect(screen.queryByText('/download_content')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '返回结果内容' }))
  expect(screen.getByRole('textbox', { name: '当前字段筛选' })).toHaveValue('device')
})

it('keeps mapping filter input mounted across result categories', async () => {
  render(<ResultsWorkspace {...props} />)
  const input = screen.getByRole('textbox', { name: '当前字段筛选' })
  fireEvent.change(input, { target: { value: 'device' } })
  fireEvent.click(screen.getByRole('tab', { name: '解析规则' }))
  await screen.findByLabelText('解析规则内容')
  fireEvent.click(screen.getByRole('tab', { name: '字段映射' }))
  expect(screen.getByRole('textbox', { name: '当前字段筛选' })).toBe(input)
  expect(input).toHaveValue('device')
})

it('blocks changing version during a pending write and has no synthetic comparison', () => {
  render(<ResultsWorkspace {...props} artifacts={[versions[1]]} blocked />)
  expect(screen.getByRole('combobox', { name: '选择产物版本' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '比较真实版本' })).toBeDisabled()
  expect(screen.queryByText(/历史示意|v1|v2/)).not.toBeInTheDocument()
})

it('uses actual task data without declaring human review completed', () => {
  const conversation: Conversation = { id: 'conv', title: '真实任务', created_at: '', updated_at: '', files: [], messages: [], runs: [{ id: 'run', status: 'succeeded' }], artifacts: [versions[1]] }
  render(<TaskOverview conversation={conversation} drafts={[]} onConversation={vi.fn()} onRun={vi.fn()} onDraft={vi.fn()} onOpen={vi.fn()} onTrace={vi.fn()} onDownload={vi.fn()} />)
  expect(screen.getByText(/1 个未匹配字段/)).toBeVisible()
  expect(screen.queryByText('审查完成')).not.toBeInTheDocument()
})

it('does not display late content from a previous artifact', async () => {
  let finish!: (value: Record<string, unknown>) => void
  vi.mocked(api.artifactContent).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ config: ['新产物'] })
  const view = render(<ResultsWorkspace {...props} />)
  fireEvent.click(screen.getByRole('tab', { name: '解析规则' }))
  await waitFor(() => expect(api.artifactContent).toHaveBeenCalled())
  view.rerender(<ResultsWorkspace {...props} artifacts={[artifact('other')]} mappingId="other" />)
  await screen.findByText(/新产物/)
  await act(async () => { finish({ config: ['旧敏感产物'] }) })
  expect(screen.queryByText(/旧敏感产物/)).not.toBeInTheDocument()
})


it('routes overview actions to confirmation, exact draft, failed run and empty conversation', () => {
  const conversation: Conversation = { id: 'conv', title: '任务', created_at: '', updated_at: '', files: [], messages: [], runs: [] }
  const onConversation = vi.fn(), onRun = vi.fn(), onDraft = vi.fn(), onOpen = vi.fn()
  const callbacks = { onConversation, onRun, onDraft, onOpen, onTrace: vi.fn(), onDownload: vi.fn() }
  const draft = { id: 'draft', conversation_id: 'conv', base_artifact_id: 'old-snapshot', revision: 1, status: 'active' as const, changed_count: 2, apply_run_id: null, applied_artifact_id: null, base_current: false }
  const view = render(<TaskOverview conversation={{...conversation, runs: [{ id: 'waiting', status: 'waiting_confirmation' }], artifacts: versions}} drafts={[draft]} {...callbacks} />)
  fireEvent.click(screen.getByRole('button', { name: '处理待确认方案' }))
  expect(onConversation).toHaveBeenCalledOnce()
  view.rerender(<TaskOverview conversation={{...conversation, artifacts: versions}} drafts={[draft]} {...callbacks} />)
  fireEvent.click(screen.getByRole('button', { name: '查看结果与草稿' }))
  expect(onDraft).toHaveBeenCalledWith(draft)
  view.rerender(<TaskOverview conversation={{...conversation, runs: [{ id: 'failed', status: 'failed' }], artifacts: versions}} drafts={[]} {...callbacks} />)
  fireEvent.click(screen.getByRole('button', { name: '查看失败原因' }))
  expect(onRun).toHaveBeenCalledWith('failed')
  view.rerender(<TaskOverview conversation={conversation} drafts={[]} {...callbacks} />)
  fireEvent.click(screen.getByRole('button', { name: '返回对话' }))
  expect(onConversation).toHaveBeenCalledTimes(2)
})

it('keeps trace references collapsed, loads only expanded runs and copies protected output references', async () => {
  const conversation: Conversation = { id: 'conv', title: '任务', created_at: '', updated_at: '', files: [], messages: [], runs: [{ id: 'run-current-snapshot', status: 'succeeded', message_id: 'message', file_id: 'file' }], artifacts: versions }
  vi.mocked(api.run).mockResolvedValue(conversation.runs[0])
  const writeText = vi.fn().mockResolvedValue(undefined)
  const previous = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  try {
    render(<ExecutionTrace conversation={conversation} onOpen={vi.fn()} onDetails={vi.fn()} />)
    expect(api.run).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '展开 业务处理' }))
    await waitFor(() => expect(api.run).toHaveBeenCalledWith('run-current-snapshot'))
    const output = screen.getByText('输出产物').closest('details')!
    expect(output.open).toBe(false)
    fireEvent.click(screen.getByText('输出产物'))
    fireEvent.click(screen.getByRole('button', { name: '复制输出引用' }))
    await screen.findByText('已复制')
    expect(JSON.parse(writeText.mock.calls[0][0])).toEqual([{ id: 'current-snapshot', kind: 'field_mapping', status: 'published' }])
    expect(api.artifactContent).not.toHaveBeenCalled()
  } finally {
    if (previous) Object.defineProperty(navigator, 'clipboard', previous)
    else Reflect.deleteProperty(navigator, 'clipboard')
  }
})

it('opens the Run selected from a conversation message inside the trace', async () => {
  const conversation: Conversation = { id: 'conv', title: '任务', created_at: '', updated_at: '', files: [], messages: [], runs: [
    { id: 'first', status: 'succeeded' }, { id: 'second', status: 'failed' }
  ] }
  vi.mocked(api.run).mockImplementation(async id => conversation.runs.find(run => run.id === id)!)
  const view = render(<ExecutionTrace conversation={conversation} onOpen={vi.fn()} onDetails={vi.fn()} targetId="second" targetToken={1} />)
  await waitFor(() => expect(api.run).toHaveBeenCalledWith('second'))
  expect(screen.getByText('second')).toBeVisible()
  expect(api.run).not.toHaveBeenCalledWith('first')
  view.rerender(<ExecutionTrace conversation={conversation} onOpen={vi.fn()} onDetails={vi.fn()} targetId="first" targetToken={2} />)
  await waitFor(() => expect(api.run).toHaveBeenCalledWith('first'))
})

it('groups runs only by their linked requirement and shows real duration, without wrapping unlinked runs', () => {
  const conversation: Conversation = { id: 'conv', title: '任务', created_at: '', updated_at: '',
    messages: [{ id: 'msg-1', actor: 'user', kind: 'text', content: '请提取日志类型并映射' }],
    files: [], runs: [
      { id: 'run-a', status: 'succeeded', kind: 'log_parse', message_id: 'msg-1', queued_at: '2026-10-26T07:00:00Z', started_at: '2026-10-26T07:00:05Z', finished_at: '2026-10-26T07:01:35Z' },
      { id: 'run-b', status: 'succeeded', kind: 'field_mapping', message_id: 'msg-1', queued_at: '2026-10-26T07:02:00Z', started_at: '2026-10-26T07:02:00Z', finished_at: '2026-10-26T07:02:45Z' },
      { id: 'run-legacy', status: 'failed', kind: 'file_ingest', queued_at: '2026-10-26T06:00:00Z', started_at: '2026-10-26T06:00:00Z', finished_at: '2026-10-26T06:00:20Z' },
    ], artifacts: [] }
  render(<ExecutionTrace conversation={conversation} onOpen={vi.fn()} onDetails={vi.fn()} />)
  expect(screen.getByText('需求：请提取日志类型并映射')).toBeInTheDocument()
  expect(screen.getByText('日志类型提取')).toBeInTheDocument()
  expect(screen.getByText('标准字段映射')).toBeInTheDocument()
  expect(screen.getByText('文件校验')).toBeInTheDocument()
  expect(screen.queryByText(/第 \d+ 组/)).not.toBeInTheDocument()
  expect(screen.getByText('1 分 30 秒')).toBeInTheDocument()
  expect(screen.getByText('45 秒')).toBeInTheDocument()
  expect(screen.getByText('20 秒')).toBeInTheDocument()
})
