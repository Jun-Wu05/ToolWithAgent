import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminConsole } from './AdminConsole'
import { api, type AdminAuditPage, type AdminKnowledgeDetail, type AdminKnowledgePage, type AdminOverview, type AdminProvider, type AdminRunPage, type AdminUser } from './api'

const identity = { id: 'dev-admin', display_name: '管理员', role: 'admin' }
const overview: AdminOverview = { runs: { queued: 2, running: 1, waiting_confirmation: 0, cancelling: 0, succeeded: 3, failed: 0, cancelled: 1 }, users: 3, conversations: 2, worker: { lease_owner: 'worker-1', lease_expires_at: '2026-10-23T00:00:00Z', epoch: 4 } }
const runsPage: AdminRunPage = { total: 2, page: 1, page_size: 50, items: [
  { id: 'run-queued-1', task_id: 't1', kind: 'log_parse', status: 'queued', attempt: 1, queued_at: '2026-10-23T00:00:00Z', started_at: null, finished_at: null, error_code: null, created_at: '2026-10-23T00:00:00Z', updated_at: '2026-10-23T00:00:00Z', owner_id: 'dev-user', owner_name: '演示用户', conversation_id: 'c1', conversation_title: '日志任务' },
  { id: 'run-running-1', task_id: 't2', kind: 'field_mapping', status: 'running', attempt: 1, queued_at: '2026-10-23T00:00:00Z', started_at: '2026-10-23T00:00:00Z', finished_at: null, error_code: null, created_at: '2026-10-23T00:00:00Z', updated_at: '2026-10-23T00:00:00Z', owner_id: 'dev-other', owner_name: '开发者', conversation_id: 'c2', conversation_title: '另一任务' },
] }
const auditPage: AdminAuditPage = { total: 1, page: 1, page_size: 50, items: [
  { id: 'a1', action: 'force_stop', target_type: 'run', target_id: 'run-running-1', created_at: '2026-10-23T00:00:00Z', reason: '异常运行', before: { status: 'running' }, after: { status: 'cancelled', error_code: 'force_stopped' }, actor_name: '管理员' },
] }
const knowledgePage: AdminKnowledgePage = { total: 2, page: 1, page_size: 20, counts: { pending: 2, approved: 0, rejected: 0 }, items: [
  { application_id: 11, status: 'pending', format_type: 'json', selection_mode: 'explicit', feature_field: 'log_type', extractor_type: 'field_path', submitter: 'dev-user', created_at: '2026-10-23T00:00:00Z', reviewed_at: null, reviewer: null, review_reason: null, replaces_application_id: null, replaced_by_application_id: null },
  { application_id: 12, status: 'pending', format_type: 'kv', selection_mode: 'automatic', feature_field: '', extractor_type: 'regex', submitter: 'dev-other', created_at: '2026-10-23T00:00:00Z', reviewed_at: null, reviewer: null, review_reason: null, replaces_application_id: null, replaced_by_application_id: null },
] }
const knowledgeDetail: AdminKnowledgeDetail = { ...knowledgePage.items[0], recipe_version: 1, structure_hash: 'abc123def456', structure_tokens: ['time', 'msg'], format_spec: { format_detail: 'json-lines' }, extractor_spec: { path: '$.log' }, submission_note: '来自冒烟验证', sample_count: 2, samples: ['2026-10-23 INFO hello', '2026-10-23 ERROR bad <tag>'] }
const providersPage: AdminProvider[] = [
  { provider: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com/v1', revision: 2, model: 'gpt-4o', updated_at: '2026-10-23T00:00:00Z', has_secret: true },
  { provider: 'deepseek', label: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', revision: 0, model: null, updated_at: null, has_secret: false },
]
const usersPage: AdminUser[] = [
  { id: 'dev-admin', display_name: '管理员', role: 'admin', active: true, created_at: '2026-10-22T00:00:00Z', conversations: 0 },
  { id: 'dev-user', display_name: '演示用户', role: 'user', active: true, created_at: '2026-10-22T00:00:00Z', conversations: 3 },
  { id: 'dev-other', display_name: '开发者', role: 'developer', active: false, created_at: '2026-10-22T00:00:00Z', conversations: 1 },
]
const props = () => ({ identity, identities: [identity, { id: 'dev-user', display_name: '演示用户', role: 'user' }], onSwitchIdentity: vi.fn(), theme: 'light' as const, onToggleTheme: vi.fn() })
beforeEach(() => {
  vi.spyOn(api, 'adminOverview').mockResolvedValue(overview)
  vi.spyOn(api, 'adminRuns').mockResolvedValue(runsPage)
  vi.spyOn(api, 'adminAuditEvents').mockResolvedValue(auditPage)
  vi.spyOn(api, 'adminCancelRun').mockResolvedValue({ id: 'run-queued-1', status: 'cancelled', error_code: 'cancelled_by_admin' })
  vi.spyOn(api, 'adminForceStop').mockResolvedValue({ id: 'run-running-1', status: 'cancelled', error_code: 'force_stopped' })
  vi.spyOn(api, 'adminKnowledge').mockResolvedValue(knowledgePage)
  vi.spyOn(api, 'adminKnowledgeDetail').mockResolvedValue(knowledgeDetail)
  vi.spyOn(api, 'adminKnowledgeApprove').mockResolvedValue({ application_id: 11, status: 'approved', replaces_application_id: null })
  vi.spyOn(api, 'adminKnowledgeReject').mockResolvedValue({ application_id: 11, status: 'rejected' })
  vi.spyOn(api, 'adminKnowledgeDelete').mockResolvedValue({ application_id: 11, status: 'deleted' })
  vi.spyOn(api, 'adminProviders').mockResolvedValue({ items: providersPage })
  vi.spyOn(api, 'adminProviderHistory').mockResolvedValue({ items: [{ revision: 2, model: 'gpt-4o', params: {}, created_at: '2026-10-23T00:00:00Z', has_secret: true }, { revision: 1, model: 'gpt-4o-mini', params: {}, created_at: '2026-10-22T00:00:00Z', has_secret: true }] })
  vi.spyOn(api, 'adminSaveProvider').mockResolvedValue({ provider: 'openai', revision: 3, model: 'gpt-4o' })
  vi.spyOn(api, 'adminTestProvider').mockResolvedValue({ ok: true, status_code: 200, latency_ms: 231 })
  vi.spyOn(api, 'adminUsers').mockResolvedValue({ items: usersPage })
  vi.spyOn(api, 'adminSetUserRole').mockResolvedValue({ id: 'dev-user', role: 'developer' })
  vi.spyOn(api, 'adminSetUserActive').mockResolvedValue({ id: 'dev-other', active: true })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('admin console', () => {
  it('shows system health metrics and worker lease on the system section', async () => {
    render(<AdminConsole {...props()} />)
    expect(await screen.findByRole('heading', { name: '系统健康' })).toBeInTheDocument()
    expect(screen.getByText('排队中')).toBeInTheDocument()
    expect(screen.getByText('Worker 租约 · 轮次 4', { selector: '.admin-metric span' })).toBeInTheDocument()
    expect(api.adminOverview).toHaveBeenCalledTimes(1)
  })
  it('lists cross-user runs with owner and conversation, and filters by status', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '运行' }))
    const table = await screen.findByRole('table', { name: '全部用户的执行记录' })
    expect(within(table).getByText('日志类型提取')).toBeInTheDocument()
    expect(within(table).getByText('演示用户')).toBeInTheDocument()
    expect(within(table).getByText('另一任务')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('运行状态筛选'), { target: { value: 'running' } })
    await waitFor(() => expect(api.adminRuns).toHaveBeenLastCalledWith('running', 1))
  })
  it('cancels a queued run and refreshes the queue and overview', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '运行' }))
    fireEvent.click(await screen.findByRole('button', { name: '取消排队' }))
    await waitFor(() => expect(api.adminCancelRun).toHaveBeenCalledWith('run-queued-1'))
    await waitFor(() => expect(vi.mocked(api.adminRuns).mock.calls.length).toBeGreaterThan(1))
    fireEvent.click(screen.getByRole('button', { name: '系统' }))
    await waitFor(() => expect(vi.mocked(api.adminOverview).mock.calls.length).toBeGreaterThan(1))
  })
  it('requires a reason before force-stopping and records the stop', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '运行' }))
    const runningRow = (await screen.findByText('标准字段映射')).closest('tr')!
    fireEvent.click(within(runningRow).getByRole('button', { name: '强停' }))
    const dialog = await screen.findByRole('dialog', { name: '确认强停执行' })
    expect(within(dialog).getByRole('button', { name: '确认强停' })).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('强停原因'), { target: { value: '卡死需要强停' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认强停' }))
    await waitFor(() => expect(api.adminForceStop).toHaveBeenCalledWith('run-running-1', '卡死需要强停'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
  it('shows the sanitized audit trail with actor, reason and status change', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '审计' }))
    const table = await screen.findByRole('table', { name: '管理操作审计记录' })
    expect(within(table).getByText('强停执行')).toBeInTheDocument()
    expect(within(table).getByText('异常运行')).toBeInTheDocument()
    expect(within(table).getByText(/\{"status":"running"\} → /)).toBeInTheDocument()
    expect(within(table).getByText('管理员')).toBeInTheDocument()
  })
  it('lists users with roles and hides self-management for the current admin', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '用户' }))
    const table = await screen.findByRole('table', { name: '用户列表' })
    expect(within(table).getByText('演示用户')).toBeInTheDocument()
    const ownRow = within(table).getByText('dev-admin', { selector: 'td small' }).closest('tr')!
    expect(within(ownRow).getByText('当前登录')).toBeInTheDocument()
    expect(within(ownRow).queryByRole('button', { name: '变更角色' })).not.toBeInTheDocument()
    expect(within(table).getAllByRole('button', { name: '变更角色' })).toHaveLength(1)
    expect(within(table).getAllByRole('button', { name: '重新启用' })).toHaveLength(1)
  })
  it('changes a user role with reason and refreshes the list', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '用户' }))
    fireEvent.click(await screen.findByRole('button', { name: '变更角色' }))
    const dialog = await screen.findByRole('dialog', { name: '变更角色 · 演示用户' })
    fireEvent.change(within(dialog).getByLabelText('新角色'), { target: { value: 'developer' } })
    fireEvent.change(within(dialog).getByLabelText('变更原因（可选，写入审计）'), { target: { value: '转岗开发' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认变更' }))
    await waitFor(() => expect(api.adminSetUserRole).toHaveBeenCalledWith('dev-user', 'developer', '转岗开发'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(vi.mocked(api.adminUsers).mock.calls.length).toBeGreaterThan(1)
  })
  it('deactivates a user after confirmation', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '用户' }))
    fireEvent.click(await screen.findByRole('button', { name: '停用' }))
    const dialog = await screen.findByRole('dialog', { name: '停用用户' })
    expect(within(dialog).getByText(/下一请求将被拒绝，进行中的执行不中断/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '取消' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '停用用户' })).not.toBeInTheDocument())
    expect(api.adminSetUserActive).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '停用' }))
    fireEvent.click(within(await screen.findByRole('dialog', { name: '停用用户' })).getByRole('button', { name: '停用' }))
    await waitFor(() => expect(api.adminSetUserActive).toHaveBeenCalledWith('dev-user', false, '停用账号'))
  })
  it('lists providers with version and secret presence, never echoing keys', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Provider' }))
    const table = await screen.findByRole('table', { name: 'Provider 列表' })
    expect(within(table).getByText('gpt-4o')).toBeInTheDocument()
    expect(within(table).getByText('已保存')).toBeInTheDocument()
    expect(within(table).getAllByText('未保存').length).toBe(1)
    expect(document.body.textContent).not.toContain('sk-')
  })
  it('saves a new provider version with a fresh key entry and reloads the list', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Provider' }))
    fireEvent.click((await screen.findAllByRole('button', { name: '配置' }))[0])
    const dialog = await screen.findByRole('dialog', { name: '配置 OpenAI' })
    fireEvent.change(within(dialog).getByLabelText('模型名称'), { target: { value: 'gpt-4o-2026' } })
    fireEvent.change(within(dialog).getByLabelText('API 密钥（必填，不回显已保存密钥）'), { target: { value: 'sk-rotated' } })
    fireEvent.change(within(dialog).getByLabelText('变更原因（可选，写入审计）'), { target: { value: '轮换密钥' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '保存新版本' }))
    await waitFor(() => expect(api.adminSaveProvider).toHaveBeenCalledWith('openai', { model: 'gpt-4o-2026', api_key: 'sk-rotated', reason: '轮换密钥' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(vi.mocked(api.adminProviders).mock.calls.length).toBeGreaterThan(1)
  })
  it('tests the saved connection without creating runs and shows latency', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Provider' }))
    fireEvent.click((await screen.findAllByRole('button', { name: '测试连接' }))[0])
    expect(await screen.findByText(/连接测试：成功/)).toBeInTheDocument()
    expect(screen.getByText(/HTTP 200/)).toBeInTheDocument()
    expect(api.adminTestProvider).toHaveBeenCalledWith('openai', {})
    expect(api.adminRuns).not.toHaveBeenCalled()
  })
  it('shows immutable version history without secrets', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Provider' }))
    fireEvent.click((await screen.findAllByRole('button', { name: '历史' }))[0])
    const dialog = await screen.findByRole('dialog', { name: '版本历史 · openai' })
    expect(await within(dialog).findByText('gpt-4o-mini')).toBeInTheDocument()
    expect(within(dialog).getAllByText('已加密保存')).toHaveLength(2)
    expect(document.body.textContent).not.toContain('sk-')
  })
  it('lists knowledge applications with submitter and opens the bounded-sample detail', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '日志知识' }))
    const table = await screen.findByRole('table', { name: '日志知识申请列表' })
    expect(within(table).getByText('#11')).toBeInTheDocument()
    expect(within(table).getByText('dev-user')).toBeInTheDocument()
    fireEvent.click(within(table).getAllByRole('button', { name: '查看' })[0])
    const dialog = await screen.findByRole('dialog', { name: '日志知识申请详情' })
    expect(await within(dialog).findByText(/"path": "\$\.log"/)).toBeInTheDocument()
    expect(within(dialog).getByText('2026-10-23 ERROR bad <tag>')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '批准' })).toBeEnabled()
    expect(within(dialog).getByRole('button', { name: '拒绝' })).toBeDisabled()
  })
  it('approves a pending application without a reason', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '日志知识' }))
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0])
    const dialog = await screen.findByRole('dialog', { name: '日志知识申请详情' })
    fireEvent.click(await within(dialog).findByRole('button', { name: '批准' }))
    await waitFor(() => expect(api.adminKnowledgeApprove).toHaveBeenCalledWith(11, undefined))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(vi.mocked(api.adminKnowledge).mock.calls.length).toBeGreaterThan(1))
  })
  it('requires a reason when approval would replace an approved competitor', async () => {
    vi.mocked(api.adminKnowledgeApprove).mockRejectedValueOnce(Object.assign(new Error('已存在同结构的已批准知识，替代它必须填写理由。'), { code: 'log_knowledge_replacement_reason_required' }))
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '日志知识' }))
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0])
    const dialog = await screen.findByRole('dialog', { name: '日志知识申请详情' })
    fireEvent.click(await within(dialog).findByRole('button', { name: '批准' }))
    expect(await within(dialog).findByText(/批准将原子替代旧知识/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '确认替代并批准' })).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('审核理由'), { target: { value: '新配方覆盖' } })
    fireEvent.click(within(dialog).getByRole('button', { name: '确认替代并批准' }))
    await waitFor(() => expect(api.adminKnowledgeApprove).toHaveBeenLastCalledWith(11, '新配方覆盖'))
  })
  it('rejects only with a reason and deletes a rejected application after confirmation', async () => {
    vi.mocked(api.adminKnowledgeDetail).mockResolvedValue({ ...knowledgeDetail, status: 'rejected', reviewer: 'dev-admin', review_reason: '样例不足' })
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '日志知识' }))
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0])
    const dialog = await screen.findByRole('dialog', { name: '日志知识申请详情' })
    expect(await within(dialog).findByText('已拒绝')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '批准' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '拒绝' })).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '删除' }))
    const confirmDialog = await screen.findByRole('dialog', { name: '删除已拒绝申请' })
    expect(within(confirmDialog).getByText(/级联清理样例，且不可恢复/)).toBeInTheDocument()
    fireEvent.click(within(confirmDialog).getByRole('button', { name: '删除' }))
    await waitFor(() => expect(api.adminKnowledgeDelete).toHaveBeenCalledWith(11))
  })
})


it('provides mobile admin navigation and preserves the independent identity switch', async () => {
  const callbacks = props()
  render(<AdminConsole {...callbacks} />)
  const toggle = screen.getByRole('button', {name: '切换管理导航'})
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  fireEvent.click(screen.getByRole('button', {name: '运行'}))
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  await screen.findByRole('table', {name: '全部用户的执行记录'})
  fireEvent.change(screen.getByRole('combobox', {name: '开发身份切换'}), {target: {value: 'dev-user'}})
  expect(callbacks.onSwitchIdentity).toHaveBeenCalledWith('dev-user')
})
