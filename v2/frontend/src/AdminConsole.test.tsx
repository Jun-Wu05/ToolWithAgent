import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminConsole } from './AdminConsole'
import { api, type AdminAuditPage, type AdminKnowledgeDetail, type AdminKnowledgePage, type AdminOverview, type AdminRunPage } from './api'

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
  it('keeps provider and user sections as explicit placeholders', async () => {
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Provider' }))
    expect(await screen.findByText(/该区域由后续切片交付/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '用户' }))
    expect(await screen.findByText(/该区域由后续切片交付/)).toBeInTheDocument()
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
    const confirm = vi.fn(() => true)
    vi.stubGlobal('confirm', confirm)
    render(<AdminConsole {...props()} />)
    fireEvent.click(await screen.findByRole('button', { name: '日志知识' }))
    fireEvent.click((await screen.findAllByRole('button', { name: '查看' }))[0])
    const dialog = await screen.findByRole('dialog', { name: '日志知识申请详情' })
    expect(await within(dialog).findByText('已拒绝')).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '批准' })).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: '拒绝' })).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: '删除' }))
    await waitFor(() => expect(api.adminKnowledgeDelete).toHaveBeenCalledWith(11))
    expect(confirm).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
