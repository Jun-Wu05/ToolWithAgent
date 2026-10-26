import { useState } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CopyButton, ContextPanel, StatusText, TaskHintBar, ToolCallBlock, fmtMs, fmtTokens } from './VisualPrimitives'

afterEach(cleanup)
describe('approved visual primitives', () => {
  it.each([['queued', '排队中'], ['running', '运行中'], ['waiting_confirmation', '等待确认'], ['failed', '失败'], ['succeeded', '已完成'], ['cancelled', '已取消'], ['constructor', '未知状态']])('pairs %s with visible text', (status, label) => {
    render(<StatusText status={status} />)
    expect(screen.getByText(label)).toBeVisible()
    expect(document.querySelector('.status-dot')).toHaveAttribute('aria-hidden', 'true')
  })
  it('leaves no task hint space when idle', () => {
    render(<TaskHintBar state={null} title="空闲" />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
  it.each(['running', 'waiting_confirmation', 'failed'] as const)('renders the %s hint with its action', state => {
    const action = vi.fn()
    render(<TaskHintBar state={state} title="规则任务" description="查看当前结果"><button onClick={action}>查看</button></TaskHintBar>)
    expect(screen.getByRole('status')).toHaveTextContent('规则任务')
    fireEvent.click(screen.getByRole('button', { name: '查看' }))
    expect(action).toHaveBeenCalledOnce()
  })
  it('keeps tool input and output collapsed until requested', () => {
    render(<ToolCallBlock name="semantic_lookup" status="succeeded" input="INPUT" output="OUTPUT" durationMs={1200} tokens={8400} />)
    const toggle = screen.getByRole('button', { name: /semantic_lookup/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('INPUT')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('INPUT')).toBeVisible()
    expect(screen.getByText('OUTPUT')).toBeVisible()
    expect(toggle).toHaveTextContent('1.2 秒 · 8.4k Token')
    fireEvent.click(toggle)
    expect(screen.queryByText('OUTPUT')).not.toBeInTheDocument()
  })
  it('uses accessible tabs, keeps tab contents and restores the initiating focus', () => {
    const origin = document.createElement('button'); document.body.append(origin); origin.focus()
    const close = vi.fn()
    const view = render(<ContextPanel panel={{ type: 'execution', id: 'r1' }} title="规则执行" onClose={close} tabs={[
      { id: 'timeline', label: '执行时间线', content: <p>步骤完成</p> },
      { id: 'io', label: '输入与输出', content: <input aria-label="未发送参数" defaultValue="草稿" /> },
    ]} />)
    const panel = screen.getByLabelText('执行详情')
    expect(within(panel).getByRole('button', { name: '关闭执行详情' })).toHaveFocus()
    const first = screen.getByRole('tab', { name: '执行时间线' })
    fireEvent.keyDown(first, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: '输入与输出' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.change(screen.getByLabelText('未发送参数'), { target: { value: '保留输入' } })
    fireEvent.keyDown(screen.getByRole('tab', { name: '输入与输出' }), { key: 'Home' })
    expect(screen.getByText('步骤完成')).toBeVisible()
    fireEvent.click(screen.getByRole('tab', { name: '输入与输出' }))
    expect(screen.getByLabelText('未发送参数')).toHaveValue('保留输入')
    fireEvent.keyDown(panel, { key: 'Escape' }); expect(close).toHaveBeenCalledOnce()
    view.unmount(); expect(origin).toHaveFocus(); origin.remove()
  })
  it.each([[null, '—'], [0, '0 ms'], [999, '999 ms'], [1000, '1.0 秒'], [61000, '1 分 1 秒']])('formats duration %s', (value, expected) => {
    expect(fmtMs(value as number | null)).toBe(expected)
  })
  it.each([[null, '—'], [0, '0'], [999, '999'], [1000, '1k'], [8400, '8.4k']])('formats token count %s', (value, expected) => {
    expect(fmtTokens(value as number | null)).toBe(expected)
  })
})


it('returns focus to the latest trigger when one context replaces another', () => {
  function SwitchingContext() {
    const [selected, setSelected] = useState<string | null>(null)
    return <><button onClick={() => setSelected('a')}>查看 A</button><button onClick={() => setSelected('b')}>查看 B</button>{selected && <ContextPanel key={selected} panel={{type: 'artifact', id: selected}} title={selected} onClose={() => setSelected(null)} tabs={[{id: 'preview', label: '内容预览', content: <p>{selected}</p>}]} />}</>
  }
  render(<SwitchingContext />)
  const a = screen.getByRole('button', {name: '查看 A'}), b = screen.getByRole('button', {name: '查看 B'})
  a.focus(); fireEvent.click(a)
  expect(screen.getByRole('button', {name: '关闭产物详情'})).toHaveFocus()
  b.focus(); fireEvent.click(b)
  fireEvent.click(screen.getByRole('button', {name: '关闭产物详情'}))
  expect(b).toHaveFocus()
})


it('traps narrow context focus, closes via mask and returns focus to the trigger', () => {
  const previous = window.matchMedia
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })) })
  try {
    const close = vi.fn()
    const trigger = document.createElement('button'); document.body.append(trigger); trigger.focus()
    const view = render(<ContextPanel panel={{type: 'task', id: 'conv'}} title="任务上下文" onClose={close} tabs={[{id: 'facts', label: '任务信息', content: <button>最后一个动作</button>}]} />)
    const panel = screen.getByRole('dialog', { name: '任务上下文' })
    const first = screen.getByRole('button', {name: '关闭任务上下文'})
    const last = screen.getByRole('button', {name: '最后一个动作'})
    last.focus(); fireEvent.keyDown(panel, {key: 'Tab'}); expect(first).toHaveFocus()
    fireEvent.keyDown(panel, {key: 'Tab', shiftKey: true}); expect(last).toHaveFocus()
    view.rerender(<ContextPanel panel={{type: 'task', id: 'conv'}} title="任务上下文" onClose={close} tabs={[
      {id: 'facts', label: '任务信息', content: <p>只有任务事实</p>},
      {id: 'artifacts', label: '产物与草稿', content: <button>隐藏页动作</button>},
    ]} />)
    const activeTab = screen.getByRole('tab', {name: '任务信息'})
    activeTab.focus(); fireEvent.keyDown(panel, {key: 'Tab'}); expect(first).toHaveFocus()
    fireEvent.keyDown(panel, {key: 'Tab', shiftKey: true}); expect(activeTab).toHaveFocus()
    fireEvent.click(screen.getByRole('button', {name: '收起任务上下文'})); expect(close).toHaveBeenCalledOnce()
    view.unmount(); expect(trigger).toHaveFocus(); trigger.remove()
  } finally { Object.defineProperty(window, 'matchMedia', {configurable: true, value: previous}) }
})

it('reports copy failure and drops a delayed success after the source changes', async () => {
  const previous = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  let finish!: () => void
  const writeText = vi.fn().mockRejectedValueOnce(new Error('denied')).mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve }))
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  try {
    const view = render(<CopyButton text="old" label="复制记录" />)
    fireEvent.click(screen.getByRole('button', {name: '复制记录'}))
    await screen.findByText('复制失败，请展开内容手动复制。')
    fireEvent.click(screen.getByRole('button', {name: '复制记录'}))
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2))
    view.rerender(<CopyButton text="new" label="复制记录" />)
    await act(async () => finish())
    expect(screen.queryByText('已复制')).not.toBeInTheDocument()
    expect(screen.queryByText(/复制失败/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', {name: '复制记录'})).toBeEnabled()
  } finally {
    if (previous) Object.defineProperty(navigator, 'clipboard', previous)
    else Reflect.deleteProperty(navigator, 'clipboard')
  }
})
