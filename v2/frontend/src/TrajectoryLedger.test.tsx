import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TrajectoryLedger } from './TrajectoryLedger'
import { api, type Conversation, type DiagnosticRun } from './api'

vi.mock('./api', () => ({ api: { run: vi.fn(), userDiagnosticRun: vi.fn(), userDiagnosticCall: vi.fn() } }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
const conversation: Conversation = {
  id: 'conv', title: '验收会话', created_at: '', updated_at: '', files: [],
  messages: [{ id: 'message-1', actor: 'user', content: '完成字段映射' }],
  runs: [{ id: 'run-1', kind: 'field_mapping', status: 'succeeded', message_id: 'message-1', queued_at: '2026-11-09T06:13:26Z', started_at: '2026-11-09T06:13:26Z', finished_at: '2026-11-09T06:14:11Z' }],
  artifacts: [],
}
const run = { ...conversation.runs[0], events: [
  { sequence: 1, scope_type: 'run', scope_id: 'run-1', event_type: 'run_started', status: 'running', created_at: '2026-11-09T06:13:26Z' },
  { sequence: 2, scope_type: 'step', scope_id: 'step-1', event_type: 'run_progress', status: 'running', summary: { phase: 'retrieval', operation: 'field_mapping', current_batch: 2, total_batches: 2 }, created_at: '2026-11-09T06:13:27Z' },
  { sequence: 3, scope_type: 'run', scope_id: 'run-1', event_type: 'run_succeeded', status: 'succeeded', created_at: '2026-11-09T06:14:11Z' },
] }
beforeEach(() => { vi.mocked(api.run).mockResolvedValue(run) })

it('shows recorded events in sequence, searches summaries and opens a bounded inspector', async () => {
  render(<TrajectoryLedger conversation={conversation} onOpen={vi.fn()} />)
  const ledger = screen.getByRole('list', { name: '事件账本' })
  await waitFor(() => expect(within(ledger).getAllByRole('listitem')).toHaveLength(4))
  expect(within(ledger).getAllByRole('button').map(item => item.textContent)).toEqual(expect.arrayContaining([expect.stringContaining('批次 2/2')]))
  fireEvent.change(screen.getByRole('textbox', { name: '搜索轨迹' }), { target: { value: '批次 2/2' } })
  expect(within(ledger).getAllByRole('listitem')).toHaveLength(1)
  fireEvent.click(within(ledger).getByRole('button', { name: '查看事件 检索候选字段' }))
  const inspector = screen.getByRole('complementary', { name: '选中事件详情' })
  expect(inspector).toHaveTextContent('step-1')
  expect(api.userDiagnosticRun).not.toHaveBeenCalled()
  fireEvent.keyDown(inspector, { key: 'Escape' })
  expect(screen.queryByRole('complementary', { name: '选中事件详情' })).not.toBeInTheDocument()
})

it('collapses repeated step events by scope and stage, and backfills status from the finished Run', async () => {
  const finished = { ...conversation.runs[0], status: 'succeeded', events: [
    { sequence: 1, scope_type: 'run', scope_id: 'run-1', event_type: 'run_started', status: 'running', created_at: '2026-11-09T06:13:26Z' },
    { sequence: 2, scope_type: 'step', scope_id: 'classify', event_type: 'run_progress', status: 'running', summary: { phase: 'model_call', pipeline_stage: 'classification', operation: 'log_classification' }, created_at: '2026-11-09T06:13:30Z' },
    { sequence: 3, scope_type: 'step', scope_id: 'classify', event_type: 'run_progress', status: 'running', summary: { phase: 'model_call', pipeline_stage: 'classification', operation: 'log_classification', current_batch: 1, total_batches: 2 }, created_at: '2026-11-09T06:13:40Z' },
    { sequence: 4, scope_type: 'step', scope_id: 'classify', event_type: 'run_progress', status: 'running', summary: { phase: 'model_call', pipeline_stage: 'classification', operation: 'log_classification', progress_status: 'success', current_batch: 2, total_batches: 2 }, created_at: '2026-11-09T06:14:00Z' },
    { sequence: 5, scope_type: 'run', scope_id: 'run-1', event_type: 'run_succeeded', status: 'succeeded', created_at: '2026-11-09T06:14:11Z' },
  ] }
  vi.mocked(api.run).mockResolvedValue(finished)
  render(<TrajectoryLedger conversation={conversation} onOpen={vi.fn()} />)
  const ledger = screen.getByRole('list', { name: '事件账本' })
  await waitFor(() => expect(within(ledger).getAllByRole('listitem')).toHaveLength(4))
  const groupRow = within(ledger).getByRole('button', { name: /日志分类/ })
  expect(groupRow).toHaveAttribute('aria-expanded', 'false')
  expect(groupRow.textContent).toContain('3 条事件')
  expect(within(ledger).queryByRole('button', { name: /查看事件 模型调用/ })).not.toBeInTheDocument()
  expect(within(ledger).queryByText('运行中')).not.toBeInTheDocument()
  fireEvent.click(groupRow)
  expect(groupRow).toHaveAttribute('aria-expanded', 'true')
  const members = within(ledger).getAllByRole('button', { name: /查看事件 模型调用/ })
  expect(members).toHaveLength(3)
  members.forEach(member => expect(member.textContent).toContain('已完成'))
})

it('localizes summaries and inspector fields so no internal English enum leaks into the ledger', async () => {
  const localized = { ...conversation.runs[0], status: 'failed', events: [
    { sequence: 1, scope_type: 'step', scope_id: 'locate', event_type: 'run_progress', status: 'running', summary: { phase: 'execution', pipeline_stage: 'feature_location', operation: 'log_classification', error_code: 'feature_location_failed' }, created_at: '2026-11-09T06:13:30Z' },
  ] }
  vi.mocked(api.run).mockResolvedValue(localized)
  render(<TrajectoryLedger conversation={conversation} onOpen={vi.fn()} />)
  const ledger = screen.getByRole('list', { name: '事件账本' })
  const row = await within(ledger).findByRole('button', { name: '查看事件 步骤进展' })
  expect(row.textContent).toContain('特征定位')
  expect(row.textContent).toContain('日志类型提取')
  expect(row.textContent).toContain('特征定位失败')
  expect(row.textContent).toContain('失败')
  expect(row.textContent).not.toContain('feature_location_failed')
  expect(row.textContent).not.toContain('log_classification')
  fireEvent.click(row)
  const inspector = screen.getByRole('complementary', { name: '选中事件详情' })
  expect(inspector).toHaveTextContent('步骤')
  expect(inspector).not.toHaveTextContent(/^.*step.*$/)
})

it('explains the timeband colors with a visible legend', async () => {
  render(<TrajectoryLedger conversation={conversation} onOpen={vi.fn()} />)
  await screen.findByRole('list', { name: '事件账本' })
  const legend = screen.getByLabelText('时间条颜色图例')
  expect(legend.textContent).toContain('已完成')
  expect(legend.textContent).toContain('进行中')
  expect(legend.textContent).toContain('失败')
})

it('reads call metadata and raw content only after explicit selection', async () => {
  const diagnostic = { calls: [{ id: 'call-1', run_id: 'run-1', task_id: 'task-1', scope_id: 'step-1', provider: 'test', model: 'test-model', operation: 'field_mapping', error_code: null }], artifacts: [], timeline: [] } as unknown as DiagnosticRun
  vi.mocked(api.userDiagnosticRun).mockResolvedValue(diagnostic)
  vi.mocked(api.userDiagnosticCall).mockResolvedValue({ ...diagnostic.calls[0], request: 'redacted by server', response: 'redacted result' })
  render(<TrajectoryLedger conversation={conversation} onOpen={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: '执行详情' }))
  fireEvent.click(screen.getByRole('button', { name: '查看模型调用' }))
  await screen.findByText('模型调用 · 1')
  expect(api.userDiagnosticCall).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: /field_mapping/ }))
  fireEvent.click(screen.getByRole('tab', { name: '参数' }))
  await screen.findByText('redacted by server')
  expect(api.userDiagnosticCall).toHaveBeenCalledWith('run-1', 'call-1')
})
