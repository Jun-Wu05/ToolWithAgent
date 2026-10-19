import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { BusinessConfirmation, BusinessOperations, RunProgress } from './BusinessWorkspace'
import { api, type Conversation } from './api'
vi.mock('./api', () => ({saveDownload: vi.fn(), api: {me: vi.fn(), identities: vi.fn(), conversations: vi.fn(), conversation: vi.fn(), eventsUrl: vi.fn(), uploadFile: vi.fn(), sendMessage: vi.fn(), operation: vi.fn(), artifactContent: vi.fn(), confirmationToken: vi.fn(), confirmRun: vi.fn(), cancelToken: vi.fn(), cancelRun: vi.fn(), run: vi.fn(), selectIdentity: vi.fn()}}))
const summary = {id: 'c1', title: '后处理任务', created_at: '', updated_at: ''}
const config = {id: 'config-1', run_id: 'r0', file_id: 'f1', kind: 'field_mapping' as const, status: 'published', current: true, config_ref: 'session.decoded_config', summary: {rule_count: 1, field_count: 1, matched_count: 1, unmatched_count: 0, parse_error_count: 0}}
const enumeration = {id: 'enum-1', run_id: 'r1', kind: 'enum_values' as const, status: 'published', current: true, summary: {item_count: 2}, result_message_id: 'answer-1', message_id: 'message-1'}
const detail: Conversation = {...summary, messages: [{id: 'answer-1', actor: 'assistant', content: '已提取枚举', run_id: 'r1'}], files: [], runs: [], artifacts: [config, enumeration], session_facts: {has_logs: true, available_config_refs: ['session.decoded_config'], enum_mapping_target_fields: ['事件结果'], referenceable_artifacts: [{artifact_type: 'enum_values', source_ref: 'session.artifacts.enum_values', source_field: 'alarm', item_count: 2, target_bindings: []}]}}
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear()
  vi.stubGlobal('EventSource', class {onmessage = null; onerror = null; close() {}})
  vi.mocked(api.me).mockResolvedValue({id: 'u1', display_name: '用户', role: 'user'})
  vi.mocked(api.identities).mockResolvedValue({items: []})
  vi.mocked(api.conversations).mockResolvedValue({items: [summary]})
  vi.mocked(api.conversation).mockResolvedValue(detail)
  vi.mocked(api.eventsUrl).mockReturnValue('/events')
  vi.mocked(api.operation).mockResolvedValue({task: {id: 't1', status: 'queued'}, run: {id: 'r2', status: 'queued'}})
  vi.mocked(api.uploadFile).mockResolvedValue({file: {id: 'f1', name: 'enum.xlsx'}, task: {id: 't1', status: 'queued'}, run: {id: 'r2', status: 'queued'}})
  vi.mocked(api.sendMessage).mockResolvedValue({id: 'message-2', actor: 'user', content: '处理日志', task: {id: 't1', status: 'queued'}, run: {id: 'r2', status: 'queued'}})
  vi.mocked(api.artifactContent).mockResolvedValue({values: ['仅本人查看的真实值']})
  vi.mocked(api.confirmationToken).mockResolvedValue({token: 'token', kind: 'business_plan', checkpoint_revision: 2, payload: {question: '执行两项操作？', operations: [{type: 'fill'}, {type: 'export'}]}})
  vi.mocked(api.confirmRun).mockResolvedValue({id: 'r2', status: 'queued'})
  vi.mocked(api.cancelToken).mockResolvedValue({token: 'cancel'})
  vi.mocked(api.cancelRun).mockResolvedValue({id: 'r2', status: 'cancelled'})
  vi.mocked(api.run).mockResolvedValue({id: 'r2', status: 'succeeded'})
})
afterEach(() => {cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals()})
it('uploads an enum attachment with its explicit role and reports natural-language task semantics', async () => {
  render(<App />); await screen.findByRole('heading', {name: '后处理任务'})
  fireEvent.change(screen.getByLabelText('上传用途'), {target: {value: 'enum_mapping'}})
  fireEvent.change(screen.getByLabelText('选择文件'), {target: {files: [new File(['x'], 'enum.xlsx')]}})
  await waitFor(() => expect(api.uploadFile).toHaveBeenCalledWith('c1', expect.objectContaining({name: 'enum.xlsx'}), 'enum_mapping'))
  await waitFor(() => expect(screen.getByLabelText('消息内容')).not.toBeDisabled())
  fireEvent.change(screen.getByLabelText('消息内容'), {target: {value: '处理日志'}}); fireEvent.click(screen.getByRole('button', {name: '发送'}))
  expect(await screen.findByText('消息已创建业务任务，执行结果将在会话中显示。')).toBeInTheDocument()
})
it('embeds results in their message and only loads owner content after a click', async () => {
  render(<App />); await screen.findByText('已提取枚举')
  expect(api.artifactContent).not.toHaveBeenCalled()
  expect(screen.getByText('2 项')).toBeInTheDocument()
  expect(screen.queryByText(/仅本人查看的真实值/)).not.toBeInTheDocument()
  const message = screen.getByText('已提取枚举').closest('article')!
  fireEvent.click(within(message).getByRole('button', {name: '查看产物'}))
  expect(await screen.findByText(/仅本人查看的真实值/)).toBeInTheDocument()
  expect(api.artifactContent).toHaveBeenCalledWith('enum-1')
  expect(screen.getAllByRole('complementary').filter(item => item.getAttribute('aria-label') === '产物详情')).toHaveLength(1)
})
it('pins the exact enum card ID and safe source reference', async () => {
  render(<BusinessOperations conversation={detail} source={enumeration} onDone={vi.fn(async () => {})} />)
  fireEvent.click(screen.getByRole('button', {name: '开始处理'}))
  await waitFor(() => expect(api.operation).toHaveBeenCalledWith('c1', {step: {step_id: 'operation', type: 'threat_mapping', source_ref: 'session.artifacts.enum_values'}, source_artifact_id: 'enum-1'}, expect.any(String)))
})
it('fills the explicit config from attachment facts without inspecting sensitive content', async () => {
  render(<BusinessOperations conversation={detail} source={config} onDone={vi.fn(async () => {})} />)
  fireEvent.change(screen.getByLabelText('处理方式'), {target: {value: 'fill'}})
  fireEvent.change(screen.getByLabelText('目标字段'), {target: {value: '事件结果'}})
  fireEvent.click(screen.getByRole('button', {name: '开始处理'}))
  await waitFor(() => expect(api.operation).toHaveBeenCalledWith('c1', {step: {step_id: 'operation', type: 'fill', fill_kind: 'enum', target_fields: ['事件结果'], config_ref: 'session.decoded_config', source_ref: 'session.enum_mapping_table'}, config_artifact_id: 'config-1'}, expect.any(String)))
  expect(api.artifactContent).not.toHaveBeenCalled()
})
it('preserves input and idempotency receipt across failed operation retries', async () => {
  vi.mocked(api.operation).mockRejectedValueOnce(new Error('暂不可用'))
  render(<BusinessOperations conversation={detail} onDone={vi.fn(async () => {})} />)
  fireEvent.change(screen.getByLabelText('目标字段'), {target: {value: 'alarm'}})
  fireEvent.click(screen.getByRole('button', {name: '开始处理'})); await screen.findByText('暂不可用')
  expect(screen.getByLabelText('目标字段')).toHaveValue('alarm')
  fireEvent.click(screen.getByRole('button', {name: '开始处理'}))
  await waitFor(() => expect(api.operation).toHaveBeenCalledTimes(2))
  expect(vi.mocked(api.operation).mock.calls[0][2]).toBe(vi.mocked(api.operation).mock.calls[1][2])
})
it('disables business operations when safe facts fail and preserves old results', async () => {
  render(<BusinessOperations conversation={{...detail, session_facts: null, session_facts_error: 'business_input_unavailable'}} source={config} onDone={vi.fn(async () => {})} />)
  expect(screen.getByRole('alert')).toHaveTextContent('当前业务输入不可用')
  expect(screen.getByRole('button', {name: '开始处理'})).toBeDisabled()
})
it('waits for confirmed publication before allowing queued text to send', async () => {
  let publish!: (value: {id: string; status: string}) => void
  vi.mocked(api.run).mockReturnValueOnce(new Promise(resolve => {publish = resolve}))
  const done = vi.fn(async () => {})
  render(<BusinessConfirmation run={{id: 'r2', status: 'waiting_confirmation'}} beforeSend onResolved={done} onBack={vi.fn()} />)
  await screen.findByText('执行两项操作？')
  fireEvent.click(screen.getByRole('button', {name: '确认完成后发送'}))
  await waitFor(() => expect(api.confirmRun).toHaveBeenCalledTimes(1)); expect(done).not.toHaveBeenCalled()
  await act(async () => publish({id: 'r2', status: 'succeeded'}))
  await waitFor(() => expect(done).toHaveBeenCalledTimes(1))
})
it('keeps the same confirmation receipt on failure and cancels through a token', async () => {
  vi.mocked(api.confirmRun).mockRejectedValueOnce(new Error('请求失败'))
  const done = vi.fn(async () => {})
  render(<BusinessConfirmation run={{id: 'r2', status: 'waiting_confirmation'}} onResolved={done} onBack={vi.fn()} />)
  await screen.findByText('执行两项操作？'); fireEvent.click(screen.getByRole('button', {name: '确认执行'})); await screen.findByText('请求失败')
  fireEvent.click(screen.getByRole('button', {name: '确认执行'})); await waitFor(() => expect(done).toHaveBeenCalled())
  expect(vi.mocked(api.confirmRun).mock.calls[0][2]).toBe(vi.mocked(api.confirmRun).mock.calls[1][2])
  fireEvent.click(screen.getByRole('button', {name: '取消执行'})); await waitFor(() => expect(api.cancelRun).toHaveBeenCalledWith('r2', 'cancel'))
})
it('preserves unsent text when confirmation fails before send', async () => {
  vi.mocked(api.conversation).mockResolvedValue({...detail, runs: [{id: 'r2', status: 'waiting_confirmation'}]})
  vi.mocked(api.confirmRun).mockRejectedValue(new Error('输入已变化'))
  render(<App />); await screen.findByRole('heading', {name: '后处理任务'})
  fireEvent.change(screen.getByLabelText('消息内容'), {target: {value: '导出下一份'}})
  fireEvent.click(screen.getByRole('button', {name: '发送'}))
  const dialog = await screen.findByRole('dialog')
  await within(dialog).findByText('执行两项操作？')
  fireEvent.click(within(dialog).getByRole('button', {name: '确认完成后发送'}))
  await within(dialog).findByText('输入已变化')
  expect(screen.getByLabelText('消息内容')).toHaveValue('导出下一份')
  expect(api.sendMessage).not.toHaveBeenCalled()
})
it('ignores owner content responses from a previous conversation', async () => {
  let oldContent!: (value: Record<string, unknown>) => void
  vi.mocked(api.artifactContent).mockReturnValueOnce(new Promise(resolve => {oldContent = resolve}))
  const other = {...summary, id: 'c2', title: '新会话'}
  vi.mocked(api.conversations).mockResolvedValue({items: [summary, other]})
  vi.mocked(api.conversation).mockImplementation(async id => id === 'c1' ? detail : {...other, messages: [], files: [], runs: []})
  render(<App />); await screen.findByText('已提取枚举'); fireEvent.click(screen.getByRole('button', {name: '查看产物'}))
  fireEvent.click(screen.getByRole('button', {name: '新会话'}))
  await screen.findByRole('heading', {name: '新会话'})
  await act(async () => oldContent({values: ['旧会话敏感值']}))
  expect(screen.queryByText(/旧会话敏感值/)).not.toBeInTheDocument()
})

it('shows safe phase and dependency labels without exposing internal scope IDs', () => {
  render(<RunProgress run={{id: 'r2', status: 'running', events: [
    {sequence: 1, scope_type: 'step', scope_id: 'hash-a', event_type: 'run_progress', status: 'running', summary: {operation: 'enum_extract', phase: 'completed', progress_status: 'success', dependency_scope_ids: []}},
    {sequence: 2, scope_type: 'step', scope_id: 'hash-b', event_type: 'run_progress', status: 'running', summary: {operation: 'threat_mapping', phase: 'validation', progress_status: 'running', dependency_scope_ids: ['hash-a']}},
    {sequence: 3, scope_type: 'run', scope_id: 'r2', event_type: 'state', status: 'running', summary: {}}
  ]}} />)
  expect(screen.getByText('枚举提取：步骤完成 已完成')).toBeInTheDocument()
  expect(screen.getByText('威胁类型映射：校验结果 进行中')).toBeInTheDocument()
  expect(screen.getByText('依赖：步骤 1')).toBeInTheDocument()
  expect(screen.queryByText(/hash-/)).not.toBeInTheDocument()
})

it('selects the threat result while retaining a config card source ID', async () => {
  const threat = {id: 'threat-1', run_id: 'r0', kind: 'threat_mapping' as const, status: 'published', current: true}
  const session: Conversation = {...detail, artifacts: [config, threat], session_facts: {...detail.session_facts!, referenceable_artifacts: [{source_ref: 'session.artifacts.threat_mapping', artifact_type: 'threat_mapping', source_field: 'alarm', item_count: 2, target_bindings: [{config_ref: 'session.decoded_config', target_field: '威胁类型'}]}]}}
  render(<BusinessOperations conversation={session} source={config} onDone={vi.fn(async () => {})} />)
  fireEvent.change(screen.getByLabelText('处理方式'), {target: {value: 'fill'}})
  fireEvent.change(screen.getByLabelText('映射来源'), {target: {value: 'threat'}})
  expect(screen.getByLabelText('来源结果')).not.toBeDisabled()
  fireEvent.change(screen.getByLabelText('来源结果'), {target: {value: 'threat-1'}})
  fireEvent.change(screen.getByLabelText('目标字段'), {target: {value: '威胁类型'}})
  fireEvent.click(screen.getByRole('button', {name: '开始处理'}))
  await waitFor(() => expect(api.operation).toHaveBeenCalledWith('c1', {step: {step_id: 'operation', type: 'fill', fill_kind: 'threat', target_fields: ['威胁类型'], config_ref: 'session.decoded_config', source_ref: 'session.artifacts.threat_mapping'}, config_artifact_id: 'config-1', source_artifact_id: 'threat-1'}, expect.any(String)))
})

it.each(['fill', 'export'] as const)('handles initial uploaded config %s before a configuration artifact exists', async kind => {
  render(<BusinessOperations conversation={{...detail, artifacts: []}} onDone={vi.fn(async () => {})} />)
  fireEvent.change(screen.getByLabelText('处理方式'), {target: {value: kind}})
  fireEvent.change(screen.getByLabelText('目标配置'), {target: {value: 'session.decoded_config'}})
  if (kind === 'fill') fireEvent.change(screen.getByLabelText('目标字段'), {target: {value: '事件结果'}})
  fireEvent.click(screen.getByRole('button', {name: '开始处理'}))
  const step = kind === 'fill' ? {step_id: 'operation', type: 'fill', fill_kind: 'enum', target_fields: ['事件结果'], config_ref: 'session.decoded_config', source_ref: 'session.enum_mapping_table'} : {step_id: 'operation', type: 'export', source_ref: 'session.decoded_config'}
  await waitFor(() => expect(api.operation).toHaveBeenCalledWith('c1', {step}, expect.any(String)))
})

it('clears through the canonical message while waiting, explaining effects and preserving unsent text', async () => {
  const confirm = vi.fn(() => true); vi.stubGlobal('confirm', confirm)
  const waiting: Conversation = {...detail, runs: [{id: 'waiting', status: 'waiting_confirmation'}], drafts: [{id: 'draft-1', conversation_id: 'c1', base_artifact_id: 'config-1', revision: 1, status: 'active', changed_count: 1, base_current: true, apply_run_id: null, applied_artifact_id: null}]}
  vi.mocked(api.conversation).mockResolvedValue(waiting)
  vi.mocked(api.sendMessage).mockResolvedValue({id: 'clear-message', actor: 'user', content: '清空数据', task: {id: 'clear-task', status: 'queued'}, run: {id: 'clear-run', kind: 'business_clear', status: 'queued'}})
  render(<App />); await screen.findByRole('heading', {name: '后处理任务'})
  fireEvent.change(screen.getByLabelText('消息内容'), {target: {value: '稍后再导出'}})
  fireEvent.click(screen.getByRole('button', {name: '清空业务数据（保留历史）'}))
  await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('c1', '清空数据', expect.any(String)))
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('取消活动执行和待确认事项、丢弃未应用草稿'))
  expect(await screen.findByText('清空业务数据已排队，历史结果和未发送文本会保留。')).toBeInTheDocument()
  expect(screen.getByLabelText('消息内容')).toHaveValue('稍后再导出')
})
it('keeps historical inputs readable without parse or mapping actions', async () => {
  vi.mocked(api.conversation).mockResolvedValue({...detail, files: [{id: 'old-input', name: 'history.log', active: false, parse_status: 'succeeded', mapping_eligible: true}], artifacts: [{...enumeration, current: false}], session_facts: {available_config_refs: [], enum_mapping_target_fields: [], referenceable_artifacts: []}})
  render(<App />); await screen.findByText('history.log')
  expect(screen.getByText(/历史输入/)).toBeInTheDocument()
  expect(screen.queryByRole('button', {name: '提取日志类型'})).not.toBeInTheDocument()
  expect(screen.queryByRole('button', {name: '标准字段映射'})).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: '查看产物'}))
  expect(await screen.findByText('仅本人查看的真实值')).toBeInTheDocument()
  expect(screen.getByRole('button', {name: '下载产物'})).toBeInTheDocument()
})
it('keeps unsent text and current inputs when clear fails', async () => {
  vi.stubGlobal('confirm', vi.fn(() => true)); vi.mocked(api.sendMessage).mockRejectedValue(new Error('清空请求失败'))
  render(<App />); await screen.findByRole('heading', {name: '后处理任务'})
  fireEvent.change(screen.getByLabelText('消息内容'), {target: {value: '待发送内容'}})
  fireEvent.click(screen.getByRole('button', {name: '清空业务数据（保留历史）'}))
  await screen.findByText('清空请求失败')
  expect(screen.getByLabelText('消息内容')).toHaveValue('待发送内容')
  expect(screen.getByText('已提取枚举')).toBeInTheDocument()
})
it('ignores a clear completion from a previous conversation', async () => {
  vi.stubGlobal('confirm', vi.fn(() => true))
  let queued!: (message: Awaited<ReturnType<typeof api.sendMessage>>) => void
  vi.mocked(api.sendMessage).mockReturnValueOnce(new Promise(resolve => {queued = resolve}))
  const other = {...summary, id: 'c2', title: '新的清空边界'}
  vi.mocked(api.conversations).mockResolvedValue({items: [summary, other]})
  vi.mocked(api.conversation).mockImplementation(async id => id === 'c1' ? detail : {...other, messages: [], files: [], runs: []})
  render(<App />); await screen.findByRole('heading', {name: '后处理任务'})
  fireEvent.click(screen.getByRole('button', {name: '清空业务数据（保留历史）'}))
  fireEvent.click(screen.getByRole('button', {name: '新的清空边界'})); await screen.findByRole('heading', {name: '新的清空边界'})
  fireEvent.change(screen.getByLabelText('消息内容'), {target: {value: '新会话内容'}})
  await act(async () => queued({id: 'clear-message', actor: 'user', content: '清空数据', run: {id: 'clear-run', status: 'queued'}}))
  expect(screen.queryByText('清空业务数据已排队，历史结果和未发送文本会保留。')).not.toBeInTheDocument()
  expect(screen.getByLabelText('消息内容')).toHaveValue('新会话内容')
})
it('uses the existing confirmation flow for exhausted recovery', async () => {
  vi.mocked(api.confirmationToken).mockResolvedValue({token: 'recovery-token', kind: 'business_plan', checkpoint_revision: 3, payload: {question: '是否继续未完成步骤？', reason_code: 'recovery_exhausted', operations: ['fill']}})
  render(<BusinessConfirmation run={{id: 'recovery-run', status: 'waiting_confirmation'}} onResolved={vi.fn(async () => {})} onBack={vi.fn()} />)
  await screen.findByRole('heading', {name: '确认继续执行'})
  expect(screen.getByText(/确认后只重试未完成步骤/)).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', {name: '确认执行'}))
  await waitFor(() => expect(api.confirmRun).toHaveBeenCalledWith('recovery-run', expect.objectContaining({token: 'recovery-token', checkpoint_revision: 3}), expect.any(String)))
})

it('retains stale classification results for owner view and download after clear', async () => {
  vi.mocked(api.conversation).mockResolvedValue({...detail, messages: [], artifacts: [{id: 'classification-old', run_id: 'old-run', file_id: 'old-file', kind: 'log_classification', status: 'stale', summary: {log_types: [{name: '登录', count: 2}], coverage: {matched_lines: 2, total_lines: 2}, rule_summary: '历史规则'}, mapping_eligible: false, submission_eligible: false}]})
  render(<App />); await screen.findByText('登录 · 2')
  fireEvent.click(screen.getByRole('button', {name: '查看产物'}))
  await waitFor(() => expect(api.artifactContent).toHaveBeenCalledWith('classification-old'))
  expect(screen.getByRole('button', {name: '下载产物'})).toBeInTheDocument()
  expect(screen.queryByRole('button', {name: '标准字段映射'})).not.toBeInTheDocument()
})

it('reuses a clear receipt on retry and uses a fresh receipt for a later explicit clear', async () => {
  vi.stubGlobal('confirm', vi.fn(() => true))
  vi.mocked(api.sendMessage).mockRejectedValueOnce(new Error('清空网络失败'))
  render(<App />); await screen.findByRole('heading', {name: '后处理任务'})
  fireEvent.click(screen.getByRole('button', {name: '清空业务数据（保留历史）'})); await screen.findByText('清空网络失败')
  fireEvent.click(screen.getByRole('button', {name: '清空业务数据（保留历史）'})); await screen.findByText('清空业务数据已排队，历史结果和未发送文本会保留。')
  await waitFor(() => expect(screen.getByRole('button', {name: '清空业务数据（保留历史）'})).not.toBeDisabled())
  expect(vi.mocked(api.sendMessage).mock.calls[0][2]).toBe(vi.mocked(api.sendMessage).mock.calls[1][2])
  fireEvent.click(screen.getByRole('button', {name: '清空业务数据（保留历史）'})); await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(3))
  expect(vi.mocked(api.sendMessage).mock.calls[2][2]).not.toBe(vi.mocked(api.sendMessage).mock.calls[1][2])
})
