import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MappingSummaryCard } from './ConversationMappingSummary'
import { api, type ApiError, type FieldMappingArtifact, type MappingDraft, type MappingDraftSummary, type MappingView } from './api'

const artifact: FieldMappingArtifact = { id: 'map-1', run_id: 'r1', file_id: 'f1', kind: 'field_mapping', status: 'published', current: true, created_at: '2026-10-22T01:00:00Z', summary: { rule_count: 1, field_count: 12, matched_count: 10, unmatched_count: 2, parse_error_count: 0 } }
const paths = ['field.10', ...Array.from({ length: 11 }, (_, i) => 'field.' + (i < 10 ? i : i + 1))]
const rows = (): MappingView => ({ artifact_id: 'map-1', sub_rules: [{ id: '0', name: '规则A', field_count: 12 }], sub_rule_id: '0', items: paths.map((path, index) => { const unmatched = path === 'field.10' || path === 'field.11'; return { source_path: path, standard_field: unmatched ? '' : `字段${index}`, samples: ['样例'], expanded_samples: [], evidence: '名称匹配', status: unmatched ? 'unmatched' as const : 'matched' as const, warning: '', user_modified: false, operation_key: `row-${path}`, sub_rule_id: '0', editable: true } }), total: 12, page: 1, page_size: 50, sample_line_reference: 'log_entry' })
const baseDraft = (): MappingDraft => ({ id: 'draft-1', conversation_id: 'conv-1', base_artifact_id: 'map-1', revision: 2, status: 'active', changed_count: 1, operation_count: 1, base_current: true, apply_run_id: null, applied_artifact_id: null, operations: [{ operation_key: 'row-field.10', proposal: { sub_rule_id: '0', source_path: 'field.10', standard_field: '目的地址', linked_sub_rule_ids: [] }, changes: [{ sub_rule_id: '0', source_path: 'field.10', standard_field: '目的地址' }] }] })
const draftSummary = (): MappingDraftSummary => ({ id: 'draft-1', conversation_id: 'conv-1', base_artifact_id: 'map-1', revision: 2, status: 'active', changed_count: 1, apply_run_id: null, applied_artifact_id: null, base_current: true })
const error = (code: string, message: string, details?: unknown) => Object.assign(new Error(message), { code, details }) as ApiError
const props = () => ({ artifact, editable: true, onOpenFull: vi.fn(), onDownload: vi.fn(), downloading: false, downloadError: '', onDraftChange: vi.fn(), onPendingChange: vi.fn() })
let stored: MappingDraft
beforeEach(() => {
  stored = baseDraft()
  vi.spyOn(api, 'mappingView').mockImplementation(async (_id, query) => {
    if (query.q) { const view = rows(); return { ...view, items: view.items.filter(row => row.source_path === query.q), total: 1 } }
    if (query.draft_id) { const view = rows(); const index = view.items.findIndex(row => row.source_path === 'field.10'); view.items[index] = { ...view.items[index], standard_field: '目的地址', status: 'matched', draft_modified: true, user_modified: true, evidence: '用户选择' }; return view }
    return rows()
  })
  vi.spyOn(api, 'mappingDraft').mockImplementation(async () => structuredClone(stored))
  vi.spyOn(api, 'createMappingDraft').mockImplementation(async () => structuredClone(stored))
  vi.spyOn(api, 'standardFields').mockResolvedValue({ items: [{ name: '源地址', category: '网络', occupied_by: null, disabled_reason: null }, { name: '目的地址', category: '网络', occupied_by: null, disabled_reason: null }] })
  vi.spyOn(api, 'saveMapping').mockImplementation(async () => ({ draft: structuredClone(stored), candidates: { source_path: '', standard_field: null, items: [] } }))
  vi.spyOn(api, 'confirmMapping').mockResolvedValue({ draft: structuredClone(stored), candidates: { source_path: '', standard_field: null, items: [] } })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })
const open = async (input = props()) => { render(<MappingSummaryCard {...input} />); await screen.findByRole('table', { name: '字段映射摘要（当前子规则）' }); return input }
const renderDraft = async () => { const input = props(); render(<MappingSummaryCard {...input} draftId={draftSummary().id} draftSummary={draftSummary()} />); await screen.findByRole('table', { name: '字段映射摘要（当前子规则）' }); return input }
const startEditing = async () => { fireEvent.click(screen.getByRole('button', { name: '行内调整' })); await screen.findByRole('combobox', { name: 'field.10 标准字段' }) }
const openChanges = async () => { fireEvent.click(screen.getByText('展开修改明细')); await screen.findByRole('table', { name: '草稿修改明细' }) }
const sourceRows = () => [...document.querySelectorAll('tr[data-source]')].map(node => node.getAttribute('data-source'))

describe('conversation mapping summary', () => {
  it('folds rows to eight by default and expands on demand', async () => {
    await open()
    expect(sourceRows()).toEqual(paths.slice(0, 8))
    fireEvent.click(screen.getByRole('button', { name: '展开全部 12 行' }))
    expect(sourceRows()).toHaveLength(12)
    fireEvent.click(screen.getByRole('button', { name: '收起摘要行' }))
    expect(sourceRows()).toHaveLength(8)
  })
  it('shows real before values from the published artifact without inventing history', async () => {
    await renderDraft()
    await openChanges()
    const changes = screen.getByRole('table', { name: '草稿修改明细' })
    expect(within(changes).getByText('field.10')).toBeInTheDocument()
    expect(within(changes).getByText('未映射')).toBeInTheDocument()
    expect(within(changes).getByText('目的地址')).toBeInTheDocument()
    expect(api.mappingView).toHaveBeenCalledWith('map-1', expect.objectContaining({ q: 'field.10', sub_rule: '0' }), expect.anything())
  })
  it('states draft status from the conversation summary without extra requests', async () => {
    render(<MappingSummaryCard {...props()} draftSummary={{ ...draftSummary(), status: 'applying' }} />)
    expect(await screen.findByText('修改正在应用，可查看执行进度。')).toBeInTheDocument()
    expect(api.mappingDraft).not.toHaveBeenCalled()
    expect(api.createMappingDraft).not.toHaveBeenCalled()
    cleanup()
    render(<MappingSummaryCard {...props()} draftSummary={{ ...draftSummary(), status: 'applied' }} />)
    expect(await screen.findByText('修改已应用为新版本。')).toBeInTheDocument()
  })
  it('edits inline through the same draft, server key and revision', async () => {
    const input = await renderDraft()
    await startEditing()
    fireEvent.click(screen.getByRole('combobox', { name: 'field.10 标准字段' }))
    fireEvent.click(screen.getByRole('option', { name: /^源地址/ }))
    await waitFor(() => expect(api.saveMapping).toHaveBeenCalledWith('draft-1', 2, 'row-field.10', { sub_rule_id: '0', source_path: 'field.10', standard_field: '源地址', linked_sub_rule_ids: [] }))
    expect(input.onDraftChange).toHaveBeenCalled()
    expect(input.onPendingChange).toHaveBeenLastCalledWith(false)
  })
  it('previews occupied targets and cancels without writing', async () => {
    vi.mocked(api.saveMapping).mockRejectedValueOnce(error('mapping_target_conflict', 'occupied', { operation_key: 'row-field.10', proposal: { sub_rule_id: '0', source_path: 'field.10', standard_field: '源地址', linked_sub_rule_ids: [] }, occupied_by: 'field.0', candidates: { source_path: 'field.10', standard_field: '源地址', items: [] } }))
    await renderDraft(); await startEditing()
    fireEvent.click(screen.getByRole('combobox', { name: 'field.10 标准字段' }))
    fireEvent.click(screen.getByRole('option', { name: /^源地址/ }))
    const modal = await screen.findByRole('dialog', { name: '确认替换映射' })
    expect(modal).toHaveTextContent('field.0')
    fireEvent.click(within(modal).getByRole('button', { name: '取消替换' }))
    expect(api.confirmMapping).not.toHaveBeenCalled()
  })
  it('retains a failed selection with an explicit retry and recovers', async () => {
    vi.mocked(api.saveMapping).mockRejectedValueOnce(error('mapping_target_invalid', '目标无效'))
    await renderDraft(); await startEditing()
    fireEvent.click(screen.getByRole('combobox', { name: 'field.10 标准字段' }))
    fireEvent.click(screen.getByRole('option', { name: /^源地址/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('目标无效')
    fireEvent.click(screen.getByRole('button', { name: '重试保存' }))
    await waitFor(() => expect(api.saveMapping).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByRole('button', { name: '重试保存' })).not.toBeInTheDocument())
  })
  it('stops writes on revision conflict until an explicit reload', async () => {
    vi.mocked(api.saveMapping).mockRejectedValueOnce(error('draft_revision_conflict', '草稿版本冲突'))
    await renderDraft(); await startEditing()
    fireEvent.click(screen.getByRole('combobox', { name: 'field.10 标准字段' }))
    fireEvent.click(screen.getByRole('option', { name: /^源地址/ }))
    await screen.findByText('草稿版本冲突')
    expect(screen.getByRole('combobox', { name: 'field.10 标准字段' })).toBeDisabled()
    stored = { ...baseDraft(), revision: 7 }
    fireEvent.click(screen.getByRole('button', { name: /重新加载草稿/ }))
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'field.10 标准字段' })).toBeEnabled())
  })
  it('surfaces view loading failures with a retry that restores the table', async () => {
    vi.mocked(api.mappingView).mockRejectedValueOnce(new Error('网络中断'))
    render(<MappingSummaryCard {...props()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('网络中断')
    fireEvent.click(screen.getByRole('button', { name: '重试加载' }))
    await screen.findByRole('table', { name: '字段映射摘要（当前子规则）' })
  })
  it('degrades honestly when a before value cannot be confirmed', async () => {
    vi.mocked(api.mappingView).mockImplementation(async (_id, query) => {
      if (query.q) throw new Error('旧值读取失败')
      return rows()
    })
    await renderDraft(); await openChanges()
    expect(await screen.findByText('—')).toBeInTheDocument()
    expect(screen.getByText(/部分修改前取值未能确认/)).toBeInTheDocument()
  })
  it('releases the pending edit lock on unmount', async () => {
    const input = props()
    render(<MappingSummaryCard {...input} draftId={draftSummary().id} draftSummary={draftSummary()} />)
    await screen.findByRole('table', { name: '字段映射摘要（当前子规则）' })
    cleanup()
    expect(input.onPendingChange).toHaveBeenLastCalledWith(false)
  })
})
