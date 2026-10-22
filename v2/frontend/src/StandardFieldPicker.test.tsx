import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { StandardFieldPicker } from './StandardFieldPicker'

afterEach(() => { cleanup(); vi.useRealTimers() })
const fields = [{ name: '源地址', category: '网络', occupied_by: 'other.ip', disabled_reason: null }, { name: '目的地址', category: '网络', occupied_by: null, disabled_reason: null }, { name: '平台字段', category: '平台', occupied_by: 'fixed', disabled_reason: 'mapping_occupant_not_editable' }]
const props = { label: 'src.ip 标准字段', source: 'src.ip', value: '', fields, disabled: false, onSelect: vi.fn() }

it('supports search, occupancy reasons and explicit keyboard commit', async () => {
  vi.useFakeTimers()
  render(<StandardFieldPicker {...props} />)
  fireEvent.click(screen.getByRole('combobox'))
  expect(screen.getByRole('option', { name: /源地址.*other.ip/ })).toBeEnabled()
  expect(screen.getByRole('option', { name: /平台字段.*平台维护/ })).toBeDisabled()
  const search = screen.getByRole('textbox', { name: '搜索标准字段' })
  fireEvent.change(search, { target: { value: '目的' } })
  fireEvent.keyDown(search, { key: 'ArrowUp' })
  const option = screen.getByRole('option', { name: /目的地址/ })
  await act(async () => { await vi.advanceTimersByTimeAsync(20) })
  expect(option).toHaveFocus()
  fireEvent.keyDown(option, { key: 'Enter' })
  expect(props.onSelect).toHaveBeenCalledWith('目的地址')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it('returns focus on Escape without committing and bounds the initial candidate list', () => {
  render(<StandardFieldPicker {...props} fields={Array.from({ length: 625 }, (_, index) => ({ name: '字段' + index, category: '网络', occupied_by: null, disabled_reason: null }))} />)
  const trigger = screen.getByRole('combobox')
  fireEvent.click(trigger)
  expect(screen.getAllByRole('option')).toHaveLength(31)
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' })
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
})
