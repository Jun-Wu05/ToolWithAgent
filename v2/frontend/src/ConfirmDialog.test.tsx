import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './ConfirmDialog'

afterEach(cleanup)

describe('ConfirmDialog 统一确认弹窗', () => {
  it('renders the title and message, focuses the cancel button on mount and confirms once', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(<ConfirmDialog title="清空业务数据" message="确认清空？" confirmLabel="清空" onConfirm={onConfirm} onCancel={onCancel} />)
    const dialog = screen.getByRole('dialog', { name: '清空业务数据' })
    expect(dialog).toHaveTextContent('确认清空？')
    const cancel = within(dialog).getByRole('button', { name: '取消' })
    expect(cancel).toHaveFocus()
    fireEvent.click(within(dialog).getByRole('button', { name: '清空' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('closes on Escape without confirming and restores focus to the previous element', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    const trigger = render(<button>触发位置</button>).getByRole('button', { name: '触发位置' })
    trigger.focus()
    const dialogRender = render(<ConfirmDialog title="停止执行" message="确认停止这次执行？已完成的正式结果会保留。" onConfirm={onConfirm} onCancel={onCancel} />)
    expect(within(screen.getByRole('dialog', { name: '停止执行' })).getByRole('button', { name: '取消' })).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('dialog', { name: '停止执行' }), { key: 'Escape' })
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
    dialogRender.unmount()
    expect(trigger).toHaveFocus()
  })

  it('falls back to the generic 确认 label when none is given', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(<ConfirmDialog title="停用用户" message="确认停用？" onConfirm={onConfirm} onCancel={onCancel} />)
    const dialog = screen.getByRole('dialog', { name: '停用用户' })
    expect(within(dialog).getByRole('button', { name: '确认' })).toBeInTheDocument()
  })
})
