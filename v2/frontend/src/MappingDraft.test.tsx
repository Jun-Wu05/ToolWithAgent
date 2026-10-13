import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MappingWorkspace } from './MappingWorkspace'
import { api, type MappingDraft, type MappingView, type MappingCandidates, type ApiError } from './api'

const artifact = { id: 'map-1', run_id: 'r1', file_id: 'f1', kind: 'field_mapping' as const, status: 'published', current: true, summary: { rule_count: 3, field_count: 2, matched_count: 1, unmatched_count: 1, parse_error_count: 0 } }
const initial = (): MappingDraft => ({ id: 'draft-1', conversation_id: 'conv-1', base_artifact_id: 'map-1', revision: 0, status: 'active', changed_count: 0, operation_count: 0, operations: [], base_current: true, apply_run_id: null, applied_artifact_id: null })
const rows = (): MappingView => ({ artifact_id: 'map-1', sub_rules: [{ id: '0', name: '当前', field_count: 2 }, { id: '1', name: '可联动', field_count: 1 }], sub_rule_id: '0', items: [
  { source_path: 'other.ip', standard_field: '源地址', samples: ['1.1.1.1'], expanded_samples: [], evidence: '名称匹配', status: 'matched', group_status: 'matched', warning: '', user_modified: false, operation_key: 'row-other', sub_rule_id: '0', editable: true },
  { source_path: 'src.ip', standard_field: '', samples: ['2.2.2.2'], expanded_samples: [], evidence: '', status: 'unmatched', group_status: 'unmatched', warning: '', user_modified: false, operation_key: 'row-src', sub_rule_id: '0', editable: true },
], total: 2, page: 1, page_size: 50, sample_line_reference: 'log_entry' })
const candidates = (): MappingCandidates => ({ source_path: 'src.ip', standard_field: '源地址', items: [
  { sub_rule_id: '1', name: '可联动', current_standard_field: '', samples: ['3.3.3.3'], selectable: true, conflict_source_path: null, selected: false },
  { sub_rule_id: '2', name: '有冲突', current_standard_field: '', samples: ['4.4.4.4'], selectable: false, conflict_source_path: 'occupied.ip', selected: false },
] })
const error = (code: string, message: string, details?: unknown) => Object.assign(new Error(message), { code, details }) as ApiError
const props = () => ({ artifact, editable: true, onBack: vi.fn(), onDownload: vi.fn(), downloading: false, downloadError: '', onPendingChange: vi.fn(), onDraftChange: vi.fn(), onApply: vi.fn(), onDiscard: vi.fn() })
let stored: MappingDraft, view: MappingView
beforeEach(() => {
  stored = initial(); view = rows()
  vi.spyOn(api, 'createMappingDraft').mockImplementation(async () => stored)
  vi.spyOn(api, 'mappingDraft').mockImplementation(async () => stored)
  vi.spyOn(api, 'mappingView').mockImplementation(async () => structuredClone(view))
  vi.spyOn(api, 'standardFields').mockResolvedValue({ items: [{ name: '源地址', category: '网络', occupied_by: 'other.ip', disabled_reason: null }, { name: '目的地址', category: '网络', occupied_by: null, disabled_reason: null }] })
  vi.spyOn(api, 'saveMapping').mockImplementation(async (_id, _revision, key, proposal) => {
    stored = { ...stored, revision: stored.revision + 1, changed_count: 1, operations: [{ operation_key: key, proposal, changes: [proposal] }] }
    view.items[1] = { ...view.items[1], standard_field: proposal.standard_field || '', status: proposal.standard_field ? 'matched' : 'unmatched', evidence: '用户选择', user_modified: true, draft_modified: true }
    return { draft: stored, candidates: { ...candidates(), items: [] } }
  })
  vi.spyOn(api, 'confirmMapping').mockImplementation(async (_id, _revision, _conflict, proposal) => ({ draft: { ...stored, revision: 1, changed_count: 2, operations: [{ operation_key: 'row-src', proposal, changes: [proposal] }] }, candidates: candidates() }))
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })
const open = async (input = props()) => { render(<MappingWorkspace {...input} />); await waitFor(() => expect(screen.getByLabelText('src.ip 标准字段')).toBeEnabled()); return input }
const choose = (target = '目的地址') => fireEvent.change(screen.getByLabelText('src.ip 标准字段'), { target: { value: target } })

describe('persistent mapping editor', () => {
  it('autosaves only the current rule using server row key and revision, preserves row group and modified evidence', async () => {
    await open(); choose()
    await screen.findByText('草稿已修改')
    expect(api.saveMapping).toHaveBeenCalledWith('draft-1', 0, 'row-src', { sub_rule_id: '0', source_path: 'src.ip', standard_field: '目的地址', linked_sub_rule_ids: [] })
    expect(api.mappingView).toHaveBeenLastCalledWith('map-1', expect.objectContaining({ draft_id: 'draft-1' }), expect.anything())
    const row = screen.getByText('src.ip').closest('tr')!
    expect(row.closest('tbody')).toHaveTextContent('未匹配')
    expect(row).toHaveTextContent('映射成功')
    expect(row).toHaveTextContent('用户选择')
    expect([...document.querySelectorAll('tr[data-source]')].map(node => node.getAttribute('data-source'))).toEqual(['other.ip', 'src.ip'])
  })
  it('restores saved marks after reopen and keeps platform-fixed rows read-only', async () => {
    stored = { ...stored, revision: 3, changed_count: 1 }
    view.items[1] = { ...view.items[1], standard_field: '目的地址', draft_modified: true, user_modified: true, evidence: '用户选择' }
    view.items[0] = { ...view.items[0], editable: false, disabled_reason: '平台固定来源' }
    render(<MappingWorkspace {...props()} draftId="draft-1" />)
    await screen.findByText('已恢复自动保存的草稿。')
    expect(await screen.findByText('草稿已修改')).toBeInTheDocument()
    expect(api.mappingDraft).toHaveBeenCalledWith('draft-1')
    expect(api.createMappingDraft).not.toHaveBeenCalled()
    expect(screen.getByLabelText('other.ip 标准字段')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'other.ip 取消映射' })).toBeDisabled()
  })
  it('previews occupied target, cancels without a write and restores focus/value', async () => {
    vi.mocked(api.saveMapping).mockRejectedValueOnce(error('mapping_target_conflict', 'occupied', { operation_key: 'row-src', proposal: { sub_rule_id: '0', source_path: 'src.ip', standard_field: '源地址', linked_sub_rule_ids: [] }, occupied_by: 'other.ip', candidates: candidates() }))
    await open(); const select = screen.getByLabelText('src.ip 标准字段'); select.focus(); choose('源地址')
    const modal = await screen.findByRole('dialog', { name: '确认替换映射' })
    expect(modal).toHaveTextContent('other.ip')
    expect(screen.getByRole('button', { name: '取消替换' })).toHaveFocus()
    expect(screen.getByRole('checkbox', { name: '联动 有冲突' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: '联动 可联动' })).not.toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: '取消替换' }))
    expect(api.confirmMapping).not.toHaveBeenCalled()
    expect(api.saveMapping).toHaveBeenCalledTimes(1)
    expect(select).toHaveValue('')
    expect(select).toHaveFocus()
  })
  it('confirms replacement and only explicitly selected eligible rules in one request', async () => {
    vi.mocked(api.saveMapping).mockRejectedValueOnce(error('mapping_target_conflict', 'occupied', { operation_key: 'row-src', proposal: { sub_rule_id: '0', source_path: 'src.ip', standard_field: '源地址', linked_sub_rule_ids: [] }, occupied_by: 'other.ip', candidates: candidates() }))
    await open(); choose('源地址'); await screen.findByRole('dialog')
    fireEvent.click(screen.getByRole('checkbox', { name: '联动 可联动' }))
    fireEvent.click(screen.getByRole('button', { name: '确认替换并保存' }))
    await screen.findByText('替换和所选联动已自动保存。')
    expect(api.confirmMapping).toHaveBeenCalledWith('draft-1', 0, expect.anything(), expect.objectContaining({ linked_sub_rule_ids: ['1'] }), true, expect.any(String))
  })
  it('keeps already-saved current-rule edit when declining optional linkage', async () => {
    vi.mocked(api.saveMapping).mockResolvedValueOnce({ draft: { ...stored, revision: 1, changed_count: 1 }, candidates: candidates() })
    await open(); choose(); await screen.findByRole('dialog', { name: '是否联动相同字段' })
    fireEvent.click(screen.getByRole('button', { name: '仅保留当前子规则' }))
    expect(screen.getByText('已保留当前子规则的修改，未新增联动。')).toBeInTheDocument()
    expect(api.saveMapping).toHaveBeenCalledTimes(1)
  })
  it('stops writes on revision conflict until explicit reload', async () => {
    vi.mocked(api.saveMapping).mockRejectedValueOnce(error('draft_revision_conflict', '草稿版本冲突'))
    await open(); choose(); await screen.findByText('草稿版本冲突')
    expect(screen.getByLabelText('src.ip 标准字段')).toBeDisabled()
    expect(screen.queryByRole('button', { name: '重试保存' })).not.toBeInTheDocument()
    stored = { ...stored, revision: 5 }
    fireEvent.click(screen.getByRole('button', { name: /重新加载草稿/ }))
    await waitFor(() => expect(screen.getByLabelText('src.ip 标准字段')).toBeEnabled())
    choose(); await screen.findByText('草稿已修改')
    expect(api.saveMapping).toHaveBeenLastCalledWith('draft-1', 5, 'row-src', expect.anything())
  })
  it('retains failed network selection and prevents sending until a retry saves it', async () => {
    const input = props()
    vi.mocked(api.saveMapping).mockRejectedValueOnce(new Error('连接中断'))
    await open(input); choose(); await screen.findByText('连接中断')
    expect(screen.getByLabelText('src.ip 标准字段')).toHaveValue('目的地址')
    expect(input.onPendingChange).toHaveBeenLastCalledWith(true)
    fireEvent.click(screen.getByRole('button', { name: '重试保存' }))
    await screen.findByText('草稿已修改')
    expect(input.onPendingChange).toHaveBeenLastCalledWith(false)
  })
  it('cancels mapping without deleting source or samples', async () => {
    await open(); fireEvent.click(screen.getByRole('button', { name: 'other.ip 取消映射' }))
    await waitFor(() => expect(api.saveMapping).toHaveBeenCalledWith('draft-1', 0, 'row-other', expect.objectContaining({ source_path: 'other.ip', standard_field: null })))
    expect(screen.getByText('other.ip')).toBeInTheDocument(); expect(screen.getByText('1.1.1.1')).toBeInTheDocument()
  })
  it('does not return to conversation until apply really resolves, retains editor on failure', async () => {
    stored = { ...stored, changed_count: 1 }
    const input = props(); let fail: (error: Error) => void = () => {}
    input.onApply.mockImplementation(() => new Promise((_resolve, reject) => { fail = reject }))
    await open(input); fireEvent.click(screen.getByRole('button', { name: '应用修改并继续' }))
    expect(input.onBack).not.toHaveBeenCalled()
    await act(async () => fail(new Error('执行失败，草稿保留')))
    await screen.findByText('执行失败，草稿保留')
    expect(input.onBack).not.toHaveBeenCalled(); expect(screen.getByText('src.ip')).toBeInTheDocument()
  })
  it('restores an applying Draft with one pending REST wait and returns only after publication', async () => {
    stored = { ...stored, status: 'applying', changed_count: 1, apply_run_id: 'apply-1' }
    const input = props(); let publish: (draft: MappingDraft) => void = () => {}
    input.onApply.mockImplementation(() => new Promise(resolve => { publish = resolve }))
    render(<MappingWorkspace {...input} draftId="draft-1" />)
    await waitFor(() => expect(input.onApply).toHaveBeenCalledTimes(1))
    expect(input.onBack).not.toHaveBeenCalled()
    expect(screen.getByLabelText('src.ip 标准字段')).toBeDisabled()
    await act(async () => publish({ ...stored, status: 'applied', applied_artifact_id: 'map-2' }))
    await waitFor(() => expect(input.onBack).toHaveBeenCalledTimes(1))
  })
  it('recovers editable Draft state when a restored application fails', async () => {
    stored = { ...stored, status: 'applying', changed_count: 1, apply_run_id: 'apply-1' }
    const input = props(); const recovered = { ...stored, status: 'active' as const, apply_run_id: null }
    input.onApply.mockRejectedValue(Object.assign(new Error('应用失败'), { mappingDraft: recovered }))
    render(<MappingWorkspace {...input} draftId="draft-1" />)
    await screen.findByText('应用失败')
    await waitFor(() => expect(screen.getByLabelText('src.ip 标准字段')).toBeEnabled())
    expect(input.onBack).not.toHaveBeenCalled(); expect(input.onDraftChange).toHaveBeenLastCalledWith(recovered)
  })
  it('allows explicit discard of a stale Draft while keeping its rows read-only', async () => {
    stored = { ...stored, changed_count: 1, base_current: false }
    const input = props(); input.onDiscard.mockResolvedValue({ ...stored, status: 'discarded', changed_count: 0 })
    render(<MappingWorkspace {...input} artifact={{ ...artifact, current: false }} draftId="draft-1" />)
    await screen.findByText('草稿来源已过期，只能查看或丢弃。')
    expect(screen.getByLabelText('src.ip 标准字段')).toBeDisabled()
    expect(screen.getByRole('button', { name: '应用修改并继续' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '丢弃草稿' }))
    await waitFor(() => expect(input.onBack).toHaveBeenCalledTimes(1))
  })
  it('shows platform-maintained linkage as read-only rather than an occupied target', async () => {
    const linked = candidates(); linked.items[1] = { ...linked.items[1], conflict_source_path: null, disabled_reason: 'mapping_source_not_editable' }
    vi.mocked(api.saveMapping).mockResolvedValueOnce({ draft: { ...stored, revision: 1, changed_count: 1 }, candidates: linked })
    await open(); choose(); await screen.findByRole('dialog')
    expect(screen.getByRole('checkbox', { name: '联动 有冲突' })).toBeDisabled()
    expect(screen.getByText('该字段不能修改，不能联动。')).toBeInTheDocument()
    expect(screen.queryByText(/目标已被.*占用，不能联动/)).not.toBeInTheDocument()
    expect(screen.queryByText('mapping_source_not_editable')).not.toBeInTheDocument()
  })
  it('ignores a save response after editor unmount', async () => {
    let complete: (result: { draft: MappingDraft; candidates: MappingCandidates }) => void = () => {}
    vi.mocked(api.saveMapping).mockImplementation(() => new Promise(resolve => { complete = resolve }))
    const input = props(); const rendered = render(<MappingWorkspace {...input} />)
    await waitFor(() => expect(screen.getByLabelText('src.ip 标准字段')).toBeEnabled()); choose()
    rendered.unmount(); input.onDraftChange.mockClear()
    await act(async () => complete({ draft: { ...stored, changed_count: 1 }, candidates: candidates() }))
    expect(input.onDraftChange).not.toHaveBeenCalled()
  })
})
