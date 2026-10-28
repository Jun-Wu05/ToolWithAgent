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
  fireEvent.click(screen.getByRole('button', { name: '失败' }))
  await waitFor(() => expect(list).toHaveBeenLastCalledWith('failed', 1))
  expect(screen.getByRole('button', { name: '失败' })).toHaveAttribute('aria-pressed', 'true')
})

it('shows an empty filtered Run history', async () => {
  vi.spyOn(api, 'userRuns').mockResolvedValue({ page: 1, page_size: 50, total: 0, items: [] })
  render(<UserHistory kind="runs" onOpen={vi.fn()} />)
  expect(await screen.findByText('当前筛选下没有执行记录。')).toBeInTheDocument()
})

it('shows a completed Run with semantic status and measured duration', async () => {
  vi.spyOn(api, 'userRuns').mockResolvedValue({ page: 1, page_size: 50, total: 1, items: [{
    id: 'run-1', task_id: 'task-1', status: 'succeeded', kind: 'field_mapping',
    conversation_id: 'conversation-1', conversation_title: '原会话',
    created_at: '2026-10-28T00:00:00Z', updated_at: '2026-10-28T00:00:02Z',
    started_at: '2026-10-28T00:00:00Z', finished_at: '2026-10-28T00:00:02Z',
  }] })
  render(<UserHistory kind="runs" onOpen={vi.fn()} />)
  expect(await screen.findByText('2.0 秒')).toHaveClass('num')
  expect(screen.getByText('已完成', { selector: '.status-text span' }).closest('.status-text')).toHaveClass('tone-success')
})
