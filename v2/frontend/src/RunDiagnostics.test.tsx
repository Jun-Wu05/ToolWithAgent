import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type AdminRunPage, type DiagnosticRun } from './api'
import { RunDiagnostics } from './RunDiagnostics'

const list: AdminRunPage = { total: 1, page: 1, page_size: 50, items: [{ id: 'run-270', task_id: 'task-270', kind: 'field_mapping', status: 'failed', attempt: 1, queued_at: '2026-10-27T00:00:00Z', started_at: null, finished_at: null, error_code: 'field_mapping_failed', created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z', owner_id: 'user-1', owner_name: '用户甲', conversation_id: 'conv-1', conversation_title: '映射任务' }] }
const detail: DiagnosticRun = {
  run: { id: 'run-270', task_id: 'task-270', kind: 'field_mapping', status: 'failed', error_code: 'field_mapping_failed', owner_name: '用户甲', conversation_title: '映射任务', queued_at: '2026-10-27T00:00:00Z', started_at: null, finished_at: null, prompt_version: 'v1', standard_field_version: 's1', provider_config_revision: 2 },
  conclusion: { status: 'failed', error_code: 'field_mapping_failed', call_id: null, scope_id: null, evidence_call_id: 'call-1', evidence_scope_id: 'step-1', possible_cause: 'model_timeout', category: 'field_mapping_failed', reason: '具体原因未采集' },
  evidence_status: '已采集',
  timeline: [{ sequence: 1, scope_type: 'step', scope_id: 'step-1', event_type: 'run_progress', status: 'running', summary: { progress_status: 'failed' }, created_at: '2026-10-27T00:00:00Z' }],
  calls: [{ id: 'call-1', run_id: 'run-270', task_id: 'task-270', scope_id: 'step-1', request_id: 'request-1', provider: 'deepseek', model: 'model-a', error_code: 'model_timeout', attempt: 2, duration_ms: 30000 }],
  logs: [{ id: 'call-call-1', level: 'error', source: 'model_call', scope_id: 'step-1', request_id: 'request-1', error_code: 'model_timeout', duration_ms: 30000, created_at: '2026-10-27T00:00:00Z' }],
  artifacts: [{ id: 'artifact-1', kind: 'field_mapping', version: 1, status: 'current', sha256: 'sha', created_at: '2026-10-27T00:00:00Z', source_artifact_ids: [] }],
}

afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Run diagnostics', () => {
  it('filters with status chips and renders a measured Run duration', async () => {
    const runs = vi.spyOn(api, 'diagnosticRuns').mockResolvedValue({ ...list, items: [{
      ...list.items[0], started_at: '2026-10-27T00:00:00Z', finished_at: '2026-10-27T00:00:02Z',
    }] })
    render(<RunDiagnostics />)
    expect(await screen.findByText('2.0 秒')).toHaveClass('num')
    expect(screen.getByText('失败', { selector: '.status-text span' }).closest('.status-text')).toHaveClass('tone-danger')
    fireEvent.click(screen.getByRole('button', { name: '已完成' }))
    await waitFor(() => expect(runs).toHaveBeenLastCalledWith('succeeded', 1))
    expect(screen.getByRole('button', { name: '已完成' })).toHaveAttribute('aria-pressed', 'true')
  })

  it.each([
    ['succeeded', '无需处理。'],
    ['running', '执行尚未结束，请刷新查看最新证据。'],
    ['cancelled', '执行已取消，可查看已保留的历史证据。'],
  ])('shows %s as an execution summary', async (status, action) => {
    vi.spyOn(api, 'diagnosticRuns').mockResolvedValue({ ...list, items: [{ ...list.items[0], status }] })
    vi.spyOn(api, 'diagnosticRun').mockResolvedValue({ ...detail, run: { ...detail.run, status }, conclusion: { ...detail.conclusion, status, category: status, call_id: null, scope_id: null } })
    vi.spyOn(api, 'diagnosticCall').mockResolvedValue(detail.calls[0])
    render(<RunDiagnostics />)
    fireEvent.click(await screen.findByRole('button', { name: 'run-270' }))
    expect(await screen.findByRole('heading', { name: '执行摘要' })).toBeInTheDocument()
    expect(screen.getByText(action)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '故障结论' })).not.toBeInTheDocument()
  })

  it('navigates linked evidence and downloads a sanitized bundle', async () => {
    vi.spyOn(api, 'diagnosticRuns').mockResolvedValue(list)
    vi.spyOn(api, 'diagnosticRun').mockResolvedValue(detail)
    vi.spyOn(api, 'diagnosticCall').mockResolvedValue({ ...detail.calls[0], request: 'safe request', response: '[REDACTED]' })
    vi.spyOn(api, 'diagnosticBundle').mockResolvedValue({ name: 'run-270-diagnostics.json', blob: new Blob(['{}']) })
    render(<RunDiagnostics />)
    fireEvent.click(await screen.findByRole('button', { name: 'run-270' }))
    expect(await screen.findByRole('heading', { name: '故障结论' })).toBeInTheDocument()
    expect(api.diagnosticCall).not.toHaveBeenCalled()
    expect(screen.getAllByRole('tab')).toHaveLength(5)
    expect(screen.getByText(/可能原因：model_timeout/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '查看失败调用证据' }))
    fireEvent.click(document.querySelector('.tool-call-summary')!)
    expect(await screen.findByText('safe request')).toBeInTheDocument()
    expect(api.diagnosticCall).toHaveBeenCalledWith('run-270', 'call-1')
    fireEvent.click(screen.getByRole('tab', { name: '日志' }))
    expect(screen.getByRole('textbox', { name: '日志关键字' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '产物' }))
    expect(screen.getByText('field_mapping · v1')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: '下载脱敏诊断包' })[0])
    await waitFor(() => expect(api.diagnosticBundle).toHaveBeenCalledWith('run-270'))
  })

  it('marks historical evidence as unavailable', async () => {
    vi.spyOn(api, 'diagnosticRuns').mockResolvedValue(list)
    vi.spyOn(api, 'diagnosticRun').mockResolvedValue({ ...detail, calls: [], evidence_status: '未采集', conclusion: { ...detail.conclusion, call_id: null, scope_id: null, category: 'field_mapping_failed', reason: '具体原因未采集' } })
    render(<RunDiagnostics />)
    fireEvent.click(await screen.findByRole('button', { name: 'run-270' }))
    expect(await screen.findByText(/具体原因未采集/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: '输入与输出' }))
    expect(screen.getAllByText('未采集').length).toBeGreaterThan(0)
  })

  it('shows a planned downstream step as grey with a bounded reason', async () => {
    vi.spyOn(api, 'diagnosticRuns').mockResolvedValue(list)
    vi.spyOn(api, 'diagnosticRun').mockResolvedValue({
      ...detail,
      planned_steps: [{ scope_id: 'step-1', operation: 'field_mapping', dependency_scope_ids: [] },
                      { scope_id: 'step-2', operation: 'export', dependency_scope_ids: ['step-1'] }],
      unexecuted_steps: [{ scope_id: 'step-2', operation: 'export', dependency_scope_ids: ['step-1'],
                           reason: 'Run 失败前未启动；具体阻断原因未采集' }],
    })
    render(<RunDiagnostics />)
    fireEvent.click(await screen.findByRole('button', { name: 'run-270' }))
    fireEvent.click(await screen.findByRole('tab', { name: '执行时间线' }))
    expect(screen.getByText(/未执行 · Run 失败前未启动/)).toHaveClass('diagnostic-unexecuted')
  })
})
