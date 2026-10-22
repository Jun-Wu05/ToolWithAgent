import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { api, type Conversation, type MappingDraft, type MappingView } from './api'
class FakeEventSource { onmessage = null; onerror = null; close() {} }
const summary = { id: 'conv-1', title: '当前会话', created_at: '', updated_at: '' }
const other = { ...summary, id: 'conv-2', title: '另一会话' }
const artifact = { id: 'map-1', run_id: 'mapping-run', file_id: 'file-1', kind: 'field_mapping' as const, status: 'published', current: true, summary: { rule_count: 1, field_count: 1, matched_count: 1, unmatched_count: 0, parse_error_count: 0 } }
const initial = (): MappingDraft => ({ id: 'draft-1', conversation_id: 'conv-1', base_artifact_id: 'map-1', revision: 2, status: 'active', changed_count: 1, operation_count: 1, operations: [], base_current: true, apply_run_id: null, applied_artifact_id: null })
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(complete => { resolve = complete }); return { promise, resolve } }
let current: MappingDraft, detail: Conversation
const update = (draft: MappingDraft) => { current = draft; detail = { ...detail, drafts: [...(detail.drafts || []).filter(item => item.id !== draft.id), { ...draft }] }; return draft }
const view = (modified: boolean): MappingView => ({ artifact_id: 'map-1', sub_rules: [{ id: '0', name: '登录', field_count: 1 }], sub_rule_id: '0', items: [{ source_path: 'src.ip', samples: ['1.1.1.1'], expanded_samples: [], standard_field: modified ? '目的地址' : '源地址', evidence: modified ? '用户选择' : '名称匹配', status: 'matched', group_status: 'matched', warning: '', user_modified: modified, draft_modified: modified, operation_key: 'source-key', sub_rule_id: '0', editable: true }], total: 1, page: 1, page_size: 50, sample_line_reference: 'log_entry' })
beforeEach(() => {
  current = initial(); detail = { ...summary, messages: [], files: [], runs: [], artifacts: [artifact], drafts: [{ ...current }] }
  sessionStorage.clear(); localStorage.clear(); vi.stubGlobal('EventSource', FakeEventSource)
  vi.spyOn(api, 'me').mockResolvedValue({ id: 'user-1', display_name: '用户一', role: 'user' })
  vi.spyOn(api, 'identities').mockResolvedValue({ items: [{ id: 'user-1', display_name: '用户一', role: 'user' }, { id: 'user-2', display_name: '用户二', role: 'user' }] })
  vi.spyOn(api, 'selectIdentity').mockResolvedValue({ id: 'user-2', display_name: '用户二', role: 'user' })
  vi.spyOn(api, 'conversations').mockResolvedValue({ items: [summary, other] })
  vi.spyOn(api, 'conversation').mockImplementation(async id => id === summary.id ? structuredClone(detail) : { ...other, messages: [], files: [], runs: [], drafts: [], artifacts: [] })
  vi.spyOn(api, 'eventsUrl').mockReturnValue('/events')
  vi.spyOn(api, 'mappingDraft').mockImplementation(async () => structuredClone(current))
  vi.spyOn(api, 'createMappingDraft').mockImplementation(async () => structuredClone(current))
  vi.spyOn(api, 'mappingView').mockImplementation(async (_id, query) => view(!!query.draft_id && current.changed_count > 0))
  vi.spyOn(api, 'standardFields').mockResolvedValue({ items: [{ name: '源地址', category: '网络', occupied_by: null, disabled_reason: null }, { name: '目的地址', category: '网络', occupied_by: null, disabled_reason: null }] })
  vi.spyOn(api, 'sendMessage').mockResolvedValue({ id: 'message-1', actor: 'user', content: '保留这条指令' })
  vi.spyOn(api, 'discardMappingDraft').mockImplementation(async id => { const item = detail.drafts!.find(draft => draft.id === id)!; const discarded = { ...current, ...item, status: 'discarded' as const, changed_count: 0 }; detail = { ...detail, drafts: detail.drafts!.map(draft => draft.id === id ? discarded : draft) }; if (current.id === id) current = discarded; return discarded })
  vi.spyOn(api, 'applyMappingDraft').mockImplementation(async () => ({ task: { id: 'task-apply', status: 'queued' }, run: { id: 'run-apply', status: 'queued' }, draft: update({ ...current, status: 'applying', apply_run_id: 'run-apply' }) }))
  vi.spyOn(api, 'run').mockResolvedValue({ id: 'run-apply', status: 'queued' })
  vi.spyOn(api, 'saveMapping').mockImplementation(async (_id, revision) => ({ draft: update({ ...current, revision: revision + 1, changed_count: 1 }), candidates: { source_path: 'src.ip', standard_field: '目的地址', items: [] } }))
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const open = async () => { render(<App />); await screen.findByRole('heading', { name: '当前会话' }); fireEvent.change(screen.getByRole('textbox', { name: '消息内容' }), { target: { value: '保留这条指令' } }) }
const chooser = async () => { fireEvent.click(screen.getByRole('button', { name: '发送' })); return screen.findByRole('dialog', { name: '发送前处理映射草稿' }) }

describe('independent mapping Draft integration boundaries', () => {
  it.each(['应用后发送', '丢弃后发送'])('stops %s if the Draft changed after the chooser snapshot, until explicit reload', async choice => {
    vi.mocked(api.run).mockImplementation(() => deferred<{ id: string; status: string }>().promise)
    await open(); await chooser(); update({ ...current, revision: 3, changed_count: 2 })
    fireEvent.click(screen.getByRole('button', { name: choice }))
    await waitFor(() => expect(api.mappingDraft).toHaveBeenCalledWith('draft-1')); await act(async () => {})
    expect(api.applyMappingDraft).not.toHaveBeenCalled(); expect(api.discardMappingDraft).not.toHaveBeenCalled(); expect(api.sendMessage).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '应用后发送' })).toBeDisabled(); expect(screen.getByRole('button', { name: '丢弃后发送' })).toBeDisabled()
    expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('保留这条指令')
    fireEvent.click(screen.getByRole('button', { name: '重新加载草稿状态' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '丢弃后发送' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await waitFor(() => expect(api.discardMappingDraft).toHaveBeenCalledWith('draft-1', 3)); await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1))
  })
  it('discards a stale Draft then applies the current one, sending only after both are resolved', async () => {
    const old = { ...current, id: 'draft-old', base_artifact_id: 'map-old', base_current: false }
    detail = { ...detail, artifacts: [{ ...artifact, id: 'map-old', current: false }, artifact], drafts: [old, { ...current }] }
    vi.mocked(api.mappingDraft).mockImplementation(async id => structuredClone(id === old.id ? old : current))
    vi.mocked(api.run).mockImplementation(async () => { update({ ...current, status: 'applied', applied_artifact_id: 'map-2' }); return { id: 'run-apply', status: 'succeeded' } })
    await open(); await chooser(); expect(screen.getByRole('button', { name: '应用后发送' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '应用后发送' })).toBeEnabled()); expect(api.sendMessage).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '应用后发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('conv-1', '保留这条指令'))
    expect(api.discardMappingDraft).toHaveBeenCalledWith('draft-old', 2); expect(api.applyMappingDraft).toHaveBeenCalledWith('draft-1', 2, expect.any(String)); expect(api.sendMessage).toHaveBeenCalledTimes(1)
  })
  it('restores an applying Draft through real App callbacks, recovers a failed Run and saves another edit', async () => {
    update({ ...current, status: 'applying', apply_run_id: 'run-apply' })
    vi.mocked(api.run).mockImplementation(async () => { update({ ...current, status: 'active', apply_run_id: null }); return { id: 'run-apply', status: 'failed', error_message: '应用校验失败' } })
    await open(); fireEvent.click(screen.getByRole('button', { name: '恢复草稿' })); await screen.findByText('应用校验失败')
    await waitFor(() => expect(screen.getByLabelText('src.ip 标准字段')).toBeEnabled())
    expect(api.applyMappingDraft).not.toHaveBeenCalled(); expect(api.run).toHaveBeenCalledWith('run-apply')
    fireEvent.click(screen.getByRole('combobox', { name: 'src.ip 标准字段' })); fireEvent.click(screen.getByRole('option', { name: /^源地址/ }))
    await waitFor(() => expect(api.saveMapping).toHaveBeenCalledWith('draft-1', 2, 'source-key', expect.objectContaining({ standard_field: '源地址' })))
    await waitFor(() => expect(screen.getByRole('button', { name: '应用修改并继续' })).toBeEnabled())
    expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('保留这条指令'); expect(api.sendMessage).not.toHaveBeenCalled()
  })
  it('ignores a late Draft creation after identity switch without attaching private rows to the new conversation', async () => {
    detail = { ...detail, drafts: [] }; const pending = deferred<MappingDraft>()
    vi.mocked(api.createMappingDraft).mockImplementationOnce(() => pending.promise)
    await open(); fireEvent.click(screen.getByRole('button', { name: '查看完整结果' })); await waitFor(() => expect(api.createMappingDraft).toHaveBeenCalledWith('map-1'))
    vi.mocked(api.me).mockResolvedValue({ id: 'user-2', display_name: '用户二', role: 'user' }); vi.mocked(api.conversations).mockResolvedValue({ items: [other] })
    fireEvent.change(screen.getByLabelText('开发身份切换'), { target: { value: 'user-2' } }); await screen.findByRole('heading', { name: '另一会话' })
    const before = vi.mocked(api.mappingView).mock.calls.length; await act(async () => pending.resolve(current))
    expect(vi.mocked(api.mappingView).mock.calls.length).toBe(before); expect(screen.queryByText('src.ip')).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: '恢复草稿' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('textbox', { name: '消息内容' }), { target: { value: '新的独立指令' } }); fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('conv-2', '新的独立指令'))
  })
  it('discards a restored Draft and reopens the formal artifact without reusing its old Draft ID', async () => {
    await open(); fireEvent.click(screen.getByRole('button', { name: '恢复草稿' })); await waitFor(() => expect(screen.getByLabelText('src.ip 标准字段')).toHaveTextContent('目的地址'))
    fireEvent.click(screen.getByRole('button', { name: '丢弃草稿' })); await screen.findByRole('button', { name: '查看完整结果' })
    vi.mocked(api.mappingView).mockClear(); vi.mocked(api.mappingDraft).mockClear()
    vi.mocked(api.createMappingDraft).mockImplementationOnce(async () => update({ ...initial(), id: 'draft-2', revision: 0, changed_count: 0, operation_count: 0 }))
    fireEvent.click(screen.getByRole('button', { name: '查看完整结果' })); await waitFor(() => expect(screen.getByLabelText('src.ip 标准字段')).toBeEnabled())
    expect(screen.getByLabelText('src.ip 标准字段')).toHaveTextContent('源地址'); expect(screen.queryByText('草稿已修改')).not.toBeInTheDocument(); expect(api.mappingDraft).not.toHaveBeenCalledWith('draft-1')
    expect(vi.mocked(api.mappingView).mock.calls.some(([, query]) => query.draft_id === 'draft-1')).toBe(false)
    expect(api.mappingView).toHaveBeenLastCalledWith('map-1', expect.objectContaining({ draft_id: 'draft-2' }), expect.anything())
  })
  it('keeps the chooser open on Escape while discard is pending, retaining text until send succeeds', async () => {
    const pending = deferred<MappingDraft>(), message = deferred<{ id: string; actor: string; content: string }>()
    vi.mocked(api.discardMappingDraft).mockImplementationOnce(() => pending.promise); vi.mocked(api.sendMessage).mockImplementationOnce(() => message.promise)
    await open(); const modal = await chooser(); expect(screen.getByRole('button', { name: '返回编辑' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' })); await waitFor(() => expect(api.discardMappingDraft).toHaveBeenCalled())
    fireEvent.keyDown(modal, { key: 'Escape' }); expect(modal).toBeInTheDocument(); expect(screen.getByRole('button', { name: '返回编辑' })).toBeDisabled(); expect(api.mappingView).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ draft_id: expect.any(String) }), expect.anything())
    await act(async () => pending.resolve(update({ ...current, status: 'discarded', changed_count: 0 }))); await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1))
    expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('保留这条指令')
    await act(async () => message.resolve({ id: 'message-1', actor: 'user', content: '保留这条指令' })); await waitFor(() => expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('')); expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
