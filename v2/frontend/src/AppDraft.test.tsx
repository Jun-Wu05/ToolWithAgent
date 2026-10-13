import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'
import { api, type MappingDraft, type Conversation, type Run } from './api'
vi.mock('./api', () => ({ saveDownload: vi.fn(), api: Object.fromEntries(['me','identities','selectIdentity','conversations','createConversation','conversation','sendMessage','uploadFile','logParse','submitLogKnowledge','retryRun','cancelToken','cancelRun','run','eventsUrl','fieldMapping','mappingView','mappingDownload','createMappingDraft','mappingDraft','standardFields','saveMapping','confirmMapping','mappingCandidates','applyMappingDraft','discardMappingDraft'].map(name => [name, vi.fn()])) }))
class FakeEventSource { onmessage = null; onerror = null; close() {} }
const summary = { id: 'conv-1', title: '当前会话', created_at: '', updated_at: '' }
const artifact = { id: 'map-1', run_id: 'r1', file_id: 'f1', kind: 'field_mapping' as const, status: 'published', current: true, summary: { rule_count: 1, field_count: 1, matched_count: 1, unmatched_count: 0, parse_error_count: 0 } }
const saved = (): MappingDraft => ({ id: 'draft-1', conversation_id: 'conv-1', base_artifact_id: 'map-1', revision: 2, status: 'active', changed_count: 1, operation_count: 1, operations: [], base_current: true, apply_run_id: null, applied_artifact_id: null })
let current: MappingDraft, detail: Conversation
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(complete => { resolve = complete }); return { promise, resolve } }
beforeEach(() => {
  current = saved(); detail = { ...summary, messages: [], files: [], runs: [], artifacts: [artifact], drafts: [current] }
  vi.stubGlobal('EventSource', FakeEventSource); sessionStorage.clear(); localStorage.clear()
  vi.mocked(api.me).mockResolvedValue({ id: 'u1', display_name: '用户一', role: 'user' })
  vi.mocked(api.identities).mockResolvedValue({ items: [{ id: 'u1', display_name: '用户一', role: 'user' }, { id: 'u2', display_name: '用户二', role: 'user' }] })
  vi.mocked(api.selectIdentity).mockResolvedValue({ id: 'u2', display_name: '用户二', role: 'user' })
  vi.mocked(api.conversations).mockResolvedValue({ items: [summary, { ...summary, id: 'conv-2', title: '另一会话' }] })
  vi.mocked(api.conversation).mockImplementation(async id => id === 'conv-1' ? detail : { ...summary, id, title: '另一会话', messages: [], files: [], runs: [] })
  vi.mocked(api.eventsUrl).mockReturnValue('/events')
  vi.mocked(api.mappingDraft).mockImplementation(async () => current)
  vi.mocked(api.createMappingDraft).mockImplementation(async () => current)
  vi.mocked(api.standardFields).mockResolvedValue({ items: [{ name: '源地址', category: '', occupied_by: null, disabled_reason: null }, { name: '目的地址', category: '', occupied_by: null, disabled_reason: null }] })
  vi.mocked(api.mappingView).mockResolvedValue({ artifact_id: 'map-1', sub_rules: [{ id: '0', name: '登录', field_count: 1 }], sub_rule_id: '0', items: [{ source_path: 'src.ip', samples: ['1.1.1.1'], expanded_samples: [], standard_field: '源地址', evidence: '用户选择', status: 'matched', warning: '', user_modified: true, draft_modified: true, operation_key: 'row-src', sub_rule_id: '0', editable: true }], total: 1, page: 1, page_size: 50, sample_line_reference: 'log_entry' })
  vi.mocked(api.sendMessage).mockResolvedValue({ id: 'message-1', actor: 'user', content: '后续指令' })
  vi.mocked(api.discardMappingDraft).mockImplementation(async id => { const item = detail.drafts!.find(draft => draft.id === id)!; Object.assign(item, { status: 'discarded', changed_count: 0 }); return { ...current, ...item } })
  vi.mocked(api.applyMappingDraft).mockImplementation(async () => { current = { ...current, status: 'applying', apply_run_id: 'apply-1' }; detail.drafts = [current]; return { task: { id: 'task-1', status: 'queued' }, run: { id: 'apply-1', status: 'queued' }, draft: current } })
  vi.mocked(api.run).mockResolvedValue({ id: 'apply-1', status: 'queued' })
})
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals() })
const open = async () => { render(<App />); await screen.findByRole('heading', { name: '当前会话' }); fireEvent.change(screen.getByRole('textbox', { name: '消息内容' }), { target: { value: '后续指令' } }) }
const send = async () => { fireEvent.click(screen.getByRole('button', { name: '发送' })); await screen.findByRole('dialog', { name: '发送前处理映射草稿' }) }

describe('Draft before sending a message', () => {
  it('returns to editing without sending or losing pending text', async () => {
    await open(); await send(); fireEvent.click(screen.getByRole('button', { name: '返回编辑' }))
    await screen.findByText('src.ip')
    expect(api.sendMessage).not.toHaveBeenCalled(); expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('后续指令')
    expect(api.mappingDraft).toHaveBeenCalledWith('draft-1')
  })
  it('discards before sending and clears text only after a successful send', async () => {
    await open(); await send(); fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('conv-1', '后续指令'))
    expect(api.discardMappingDraft).toHaveBeenCalledWith('draft-1', 2)
    expect(api.discardMappingDraft).toHaveBeenCalledBefore(vi.mocked(api.sendMessage))
    await waitFor(() => expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue(''))
  })
  it('waits for succeeded Run and published Draft before apply-then-send', async () => {
    const run = deferred<Run>(), draft = deferred<MappingDraft>()
    await open(); await send()
    vi.mocked(api.mappingDraft).mockImplementationOnce(async () => current).mockImplementationOnce(() => draft.promise)
    vi.mocked(api.run).mockImplementationOnce(() => run.promise)
    fireEvent.click(screen.getByRole('button', { name: '应用后发送' }))
    await waitFor(() => expect(api.applyMappingDraft).toHaveBeenCalled())
    expect(api.sendMessage).not.toHaveBeenCalled(); expect(screen.getByRole('dialog')).toBeInTheDocument()
    current = { ...current, status: 'applied', applied_artifact_id: 'map-2' }; detail.drafts = [current]
    await act(async () => { run.resolve({ id: 'apply-1', status: 'succeeded' }); draft.resolve(current) })
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('conv-1', '后续指令'))
    expect(api.applyMappingDraft).toHaveBeenCalledWith('draft-1', 2, expect.any(String))
  })
  it('accepts a published Draft when the parallel Run read still reports queued', async () => {
    await open(); await send()
    const published = { ...current, status: 'applied' as const, apply_run_id: 'apply-1', applied_artifact_id: 'map-2' }
    vi.mocked(api.mappingDraft).mockImplementationOnce(async () => current).mockImplementationOnce(async () => { detail.drafts = [published]; return published })
    vi.mocked(api.run).mockResolvedValueOnce({ id: 'apply-1', status: 'queued' })
    fireEvent.click(screen.getByRole('button', { name: '应用后发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('conv-1', '后续指令'))
    expect(screen.queryByText('修改未应用，草稿已恢复，请检查后重试。')).not.toBeInTheDocument()
  })
  it('follows a resumed Run instead of treating an old Run failure as current', async () => {
    await open(); await send()
    const resumed = { ...current, status: 'applying' as const, apply_run_id: 'apply-2' }
    const published = { ...resumed, status: 'applied' as const, applied_artifact_id: 'map-2' }
    vi.mocked(api.mappingDraft).mockImplementationOnce(async () => current).mockImplementationOnce(async () => resumed).mockImplementationOnce(async () => { detail.drafts = [published]; return published })
    vi.mocked(api.run).mockResolvedValueOnce({ id: 'apply-1', status: 'failed', error_message: '旧执行失败' }).mockResolvedValueOnce({ id: 'apply-2', status: 'succeeded' })
    fireEvent.click(screen.getByRole('button', { name: '应用后发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1))
    expect(api.run).toHaveBeenNthCalledWith(2, 'apply-2')
    expect(screen.queryByText('旧执行失败')).not.toBeInTheDocument()
  })
  it('keeps pending text when Draft revision changes while waiting for apply', async () => {
    await open(); await send()
    vi.mocked(api.mappingDraft).mockImplementationOnce(async () => current).mockImplementationOnce(async () => ({ ...current, revision: 3 }))
    fireEvent.click(screen.getByRole('button', { name: '应用后发送' }))
    await screen.findByText('草稿已更新，已停止等待旧版本。请重新加载草稿。')
    expect(api.sendMessage).not.toHaveBeenCalled(); expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('后续指令')
  })
  it('retains text and chooser when apply fails; explicit retry gets a fresh receipt', async () => {
    vi.mocked(api.run).mockImplementation(async () => { current = { ...current, status: 'active', apply_run_id: null }; detail.drafts = [current]; return { id: 'apply-1', status: 'failed', error_message: '校验失败' } })
    await open(); await send(); fireEvent.click(screen.getByRole('button', { name: '应用后发送' }))
    await screen.findByText('校验失败')
    expect(api.sendMessage).not.toHaveBeenCalled(); expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('后续指令')
    const first = vi.mocked(api.applyMappingDraft).mock.calls[0][2]
    fireEvent.click(screen.getByRole('button', { name: '应用后发送' }))
    await waitFor(() => expect(api.applyMappingDraft).toHaveBeenCalledTimes(2))
    expect(vi.mocked(api.applyMappingDraft).mock.calls[1][2]).not.toBe(first)
  })
  it('retains pending text on a send network error after discard', async () => {
    vi.mocked(api.sendMessage).mockRejectedValueOnce(new Error('消息连接中断'))
    await open(); await send(); fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await screen.findByText('消息连接中断')
    expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('后续指令')
  })
  it('explicitly processes multiple Drafts including stale bases without blocking forever', async () => {
    detail.drafts = [{ ...current, base_current: false }, { ...current, id: 'draft-2', base_artifact_id: 'map-old', base_current: false }]
    vi.mocked(api.mappingDraft).mockImplementation(async id => ({ ...current, ...detail.drafts!.find(item => item.id === id)! }))
    await open(); await send(); expect(screen.getByRole('button', { name: '应用后发送' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await waitFor(() => expect(api.discardMappingDraft).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByRole('button', { name: '丢弃后发送' })).toBeEnabled())
    expect(api.sendMessage).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1))
    expect(api.discardMappingDraft).toHaveBeenNthCalledWith(2, 'draft-2', 2)
  })
  it('recovers server draft_resolution_required and presents the choices without swallowing text', async () => {
    detail.drafts = []
    vi.mocked(api.sendMessage).mockImplementationOnce(async () => { detail.drafts = [current]; throw Object.assign(new Error('pending Draft'), { code: 'draft_resolution_required' }) })
    await open(); fireEvent.click(screen.getByRole('button', { name: '发送' }))
    await screen.findByRole('dialog', { name: '发送前处理映射草稿' })
    expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('后续指令')
    fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(2))
  })
  it.each(['conversation', 'identity'])('ignores delayed Draft discard after switching %s and preserves the new Composer', async target => {
    const pending = deferred<MappingDraft>()
    await open(); await send(); vi.mocked(api.mappingDraft).mockImplementationOnce(() => pending.promise)
    fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    if (target === 'conversation') fireEvent.click(screen.getByRole('button', { name: /另一会话/ }))
    else {
      vi.mocked(api.me).mockResolvedValue({ id: 'u2', display_name: '用户二', role: 'user' })
      vi.mocked(api.conversations).mockResolvedValue({ items: [{ ...summary, id: 'conv-2', title: '另一会话' }] })
      fireEvent.change(screen.getByLabelText('开发身份切换'), { target: { value: 'u2' } })
    }
    await screen.findByRole('heading', { name: '另一会话' })
    fireEvent.change(screen.getByRole('textbox', { name: '消息内容' }), { target: { value: '新页面文字' } })
    await act(async () => pending.resolve(current))
    expect(api.discardMappingDraft).not.toHaveBeenCalled(); expect(api.sendMessage).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox', { name: '消息内容' })).toHaveValue('新页面文字')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
  it('does not send an old queued apply result after switching conversation', async () => {
    const run = deferred<Run>(), draft = deferred<MappingDraft>()
    await open(); await send(); vi.mocked(api.mappingDraft).mockImplementationOnce(async () => current).mockImplementationOnce(() => draft.promise); vi.mocked(api.run).mockImplementationOnce(() => run.promise)
    fireEvent.click(screen.getByRole('button', { name: '应用后发送' })); await waitFor(() => expect(api.run).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /另一会话/ })); await screen.findByRole('heading', { name: '另一会话' })
    await act(async () => { run.resolve({ id: 'apply-1', status: 'succeeded' }); draft.resolve({ ...current, status: 'applied', applied_artifact_id: 'map-2' }) })
    expect(api.sendMessage).not.toHaveBeenCalled(); expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
  it('blocks Composer while an edit save is pending and keeps text on save failure', async () => {
    current = { ...current, changed_count: 0 }; detail.drafts = [current]
    const save = deferred<never>(); vi.mocked(api.saveMapping).mockImplementationOnce(() => save.promise)
    await open(); fireEvent.click(screen.getByRole('button', { name: '查看结果' })); await waitFor(() => expect(screen.getByLabelText('src.ip 标准字段')).toBeEnabled())
    fireEvent.change(screen.getByLabelText('src.ip 标准字段'), { target: { value: '目的地址' } })
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
    fireEvent.keyDown(screen.getByRole('textbox', { name: '消息内容' }), { key: 'Enter' })
    expect(api.sendMessage).not.toHaveBeenCalled()
  })
  it('stops draft resolution writes after a revision conflict until explicit reload', async () => {
    vi.mocked(api.discardMappingDraft).mockRejectedValueOnce(Object.assign(new Error('草稿版本冲突'), { code: 'draft_revision_conflict' }))
    await open(); await send(); fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await screen.findByText('草稿版本冲突')
    expect(screen.getByRole('button', { name: '丢弃后发送' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '应用后发送' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '重新加载草稿状态' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '丢弃后发送' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '丢弃后发送' }))
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(1))
  })
  it('does not send after a delayed conversation creation changes view', async () => {
    vi.mocked(api.conversations).mockResolvedValue({ items: [] }); const creation = deferred<typeof summary>(); vi.mocked(api.createConversation).mockImplementationOnce(() => creation.promise)
    render(<App />); await screen.findByRole('heading', { name: '开始一项日志规则任务' })
    fireEvent.change(screen.getByRole('textbox', { name: '消息内容' }), { target: { value: '旧指令' } }); fireEvent.click(screen.getByRole('button', { name: '发送' }))
    vi.mocked(api.me).mockResolvedValue({ id: 'u2', display_name: '用户二', role: 'user' }); vi.mocked(api.conversations).mockResolvedValue({ items: [{ ...summary, id: 'conv-2', title: '另一会话' }] })
    fireEvent.change(screen.getByLabelText('开发身份切换'), { target: { value: 'u2' } }); await screen.findByRole('heading', { name: '另一会话' })
    await act(async () => creation.resolve(summary)); expect(api.sendMessage).not.toHaveBeenCalled(); expect(screen.getByRole('heading', { name: '另一会话' })).toBeInTheDocument()
  })
})
