import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { UserHistory } from './UserHistory'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('filters owner Task history and returns to the source Run', async () => {
  const list = vi.spyOn(api, 'userTasks').mockResolvedValue({ page: 1, page_size: 50, total: 1, items: [{
    id: 'task-1', type: 'user_request', status: 'queued', current_run_id: 'run-1',
    conversation_id: 'conversation-1', conversation_title: '原会话', message_id: 'message-1',
    file_id: null, attempt: 1, created_at: '2026-10-28T00:00:00Z', updated_at: '2026-10-28T00:00:00Z',
  }] })
  const open = vi.fn()
  render(<UserHistory kind="tasks" onOpen={open} />)
  fireEvent.click(await screen.findByRole('button', { name: '回到原会话并查看执行' }))
  expect(open).toHaveBeenCalledWith('conversation-1', 'run-1', 'message-1')
  fireEvent.change(screen.getByRole('combobox', { name: '历史状态' }), { target: { value: 'failed' } })
  await waitFor(() => expect(list).toHaveBeenLastCalledWith('failed', 1))
})

it('shows an empty filtered Run history', async () => {
  vi.spyOn(api, 'userRuns').mockResolvedValue({ page: 1, page_size: 50, total: 0, items: [] })
  render(<UserHistory kind="runs" onOpen={vi.fn()} />)
  expect(await screen.findByText('当前筛选下没有执行记录。')).toBeInTheDocument()
})
