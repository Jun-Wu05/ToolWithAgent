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
