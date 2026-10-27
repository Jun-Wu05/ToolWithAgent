import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MappingWorkspace } from './MappingWorkspace'
import { api, saveDownload, type MappingView } from './api'

const view = (overrides: Partial<MappingView> = {}): MappingView => ({
  artifact_id: 'map-1', sub_rules: [{ id: '0', name: '登录事件', field_count: 51 }, { id: '1', name: '网络事件', field_count: 2 }],
  sub_rule_id: '0', items: [{ source_path: 'src_ip', samples: ['10.0.0.1', '10.0.0.2', '10.0.0.3'],
    expanded_samples: [{ value: '10.0.0.1', line_number: 2 }, { value: '10.0.0.2', line_number: 5 }, { value: '10.0.0.3', line_number: 7 }, { value: '10.0.0.4', line_number: 12 }],
    standard_field: '源地址', evidence: '名称与样例匹配', status: 'matched', warning: '', user_modified: false }],
  total: 51, page: 1, page_size: 50, sample_line_reference: 'log_entry', ...overrides,
})
const props = { artifact: { id: 'map-1', run_id: 'r1', file_id: 'f1', kind: 'field_mapping' as const, status: 'published', current: true,
  summary: { rule_count: 2, field_count: 53, matched_count: 51, unmatched_count: 2, parse_error_count: 0 } },
  onBack: vi.fn(), onDownload: vi.fn(), downloading: false, downloadError: '' }
const reply = (body: MappingView) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
beforeEach(() => { vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(reply(view())))) })
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })

describe('mapping result view', () => {
  it('shows read-only grouped evidence and log entry references for expanded samples', async () => {
    render(<MappingWorkspace {...props} />)
    await screen.findByText('src_ip')
    expect(screen.getByRole('table')).toHaveTextContent('源地址')
    expect(screen.getByRole('table')).toHaveTextContent('映射成功')
    fireEvent.click(screen.getByText('查看更多样例'))
    expect(screen.getByText('日志条目 12')).toBeInTheDocument()
    expect(screen.queryByText(/Excel 行/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '应用修改并继续' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '取消映射' })).not.toBeInTheDocument()
  })
  it('shows final protected annotations and threat warnings, retaining them when a query fails', async () => {
    vi.mocked(fetch).mockImplementation(() => Promise.resolve(reply(view({
      event_annotations: [
        { rule_name: '已判定子规则', event_name: '网络攻击事件', event_level: '高', threat_source_field: 'nested.description', threat_types: ['拒绝服务', '漏洞利用'], status: 'judged' },
        { rule_name: '需确认子规则', event_name: '', event_level: 'unknown', threat_source_field: '', threat_types: [], status: 'uncertain' },
      ],
      warnings: [{ code: 'threat_chain_warning', message: '⚠️ 本次威胁类型未生成，请检查来源。' }],
    }))))
    render(<MappingWorkspace {...props} />)
    const disclosure = await screen.findByText('事件名称标注 · 2 条')
    fireEvent.click(disclosure)
    const annotations = await screen.findByRole('table', { name: '事件名称标注' })
    expect(annotations).toHaveTextContent('网络攻击事件')
    expect(annotations).toHaveTextContent('日志字段 nested.description')
    expect(annotations).toHaveTextContent('拒绝服务、漏洞利用')
    expect(annotations).toHaveTextContent('已判定')
    expect(annotations).toHaveTextContent('待人工确认')
    expect(annotations).toHaveTextContent('未知')
    expect(annotations).toHaveTextContent('未确定')
    expect(annotations).toHaveTextContent('未生成')
    expect(screen.getByText('⚠️ 本次威胁类型未生成，请检查来源。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /确认标注|应用修改|编辑标注/ })).not.toBeInTheDocument()
    vi.mocked(fetch).mockRejectedValueOnce(new Error('查询失败'))
    fireEvent.click(screen.getByRole('tab', { name: /网络事件/ }))
    await screen.findByText('查询失败')
    expect(screen.getByRole('table', { name: '事件名称标注' })).toHaveTextContent('网络攻击事件')
    expect(screen.getByText('⚠️ 本次威胁类型未生成，请检查来源。')).toBeInTheDocument()
  })
  it('requests whole-rule filters and page 2 rather than filtering the displayed page', async () => {
    render(<MappingWorkspace {...props} />)
    await screen.findByText('src_ip')
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('page=2'), expect.objectContaining({ credentials: 'include' })))
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索字段或样例' }), { target: { value: 'target' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringMatching(/page=1.*q=target/), expect.anything()))
    fireEvent.change(screen.getByLabelText('状态筛选'), { target: { value: 'unmatched' } })
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('status=unmatched'), expect.anything()))
    fireEvent.click(screen.getByRole('tab', { name: /网络事件/ }))
    await waitFor(() => expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining('sub_rule=1'), expect.anything()))
  })
  it('ignores an old artifact response after changing the opened artifact', async () => {
    let resolveOld: (response: Response) => void = () => {}
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockImplementation(() => Promise.resolve(reply(view({ artifact_id: 'map-2', items: [], total: 0 }))))
    const rendered = render(<MappingWorkspace {...props} />)
    rendered.rerender(<MappingWorkspace {...props} artifact={{ ...props.artifact, id: 'map-2' }} />)
    await screen.findByText('没有符合条件的字段。')
    await act(async () => resolveOld(reply(view())))
    expect(screen.queryByText('src_ip')).not.toBeInTheDocument()
  })
  it('offers retry and marks a stale result without removing download access', async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error('连接中断'))
    render(<MappingWorkspace {...props} artifact={{ ...props.artifact, status: 'stale', current: false }} />)
    await screen.findByText('连接中断')
    expect(screen.getByText(/结果已过期/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '重试加载' }))
    await screen.findByText('src_ip')
    fireEvent.click(screen.getByRole('button', { name: '下载配置' }))
    expect(props.onDownload).toHaveBeenCalledOnce()
    fireEvent.click(screen.getByRole('button', { name: '返回对话' }))
    expect(props.onBack).toHaveBeenCalledOnce()
  })
  it.each(['search', 'filter', 'pagination'])('keeps %s scoped to the visible tab after a newer tab query fails', async action => {
    render(<MappingWorkspace {...props} />)
    await screen.findByText('src_ip')
    vi.mocked(fetch).mockRejectedValueOnce(new Error('搜索失败'))
    fireEvent.click(screen.getByRole('tab', { name: /网络事件/ }))
    await screen.findByText('搜索失败')
    expect(screen.getByRole('table')).toHaveTextContent('src_ip')
    expect(screen.getByRole('tab', { name: /登录事件/ })).toHaveAttribute('aria-selected', 'true')
    if (action === 'search') {
      fireEvent.change(screen.getByRole('searchbox', { name: '搜索字段或样例' }), { target: { value: 'src_ip' } })
      fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    } else if (action === 'filter') {
      fireEvent.change(screen.getByLabelText('状态筛选'), { target: { value: 'unmatched' } })
    } else {
      fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    }
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3))
    const request = new URL(String(vi.mocked(fetch).mock.calls.at(-1)![0]), 'http://localhost')
    expect(request.searchParams.get('sub_rule') || '0').toBe('0')
  })
  it('ignores slower query results after a newer filter has loaded', async () => {
    render(<MappingWorkspace {...props} />)
    await screen.findByText('src_ip')
    let resolveOld: (response: Response) => void = () => {}
    vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockImplementation(() => Promise.resolve(reply(view({ items: [], total: 0 }))))
    fireEvent.change(screen.getByRole('searchbox', { name: '搜索字段或样例' }), { target: { value: 'missing' } })
    fireEvent.click(screen.getByRole('button', { name: '搜索' }))
    fireEvent.change(screen.getByLabelText('状态筛选'), { target: { value: 'parse_error' } })
    await screen.findByText('没有符合条件的字段。')
    await act(async () => resolveOld(reply(view())))
    expect(screen.queryByText('src_ip')).not.toBeInTheDocument()
  })
})

describe('protected artifact API', () => {
  it.each([['mapping_input_stale', '主数据或分类结果已变化，请重新选择当前输入。'], ['data_source_fields_required', '请填写产品和厂商。']])('renders a human-readable %s error', async (code, message) => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ error: { code, message: code } }), { status: 400 }))
    await expect(api.fieldMapping('conv-1', { file_id: 'f1', product: '产品', log_vendor: '厂商' }, 'retry-key')).rejects.toMatchObject({ message, code })
    expect(fetch).toHaveBeenCalledWith('/api/v2/conversations/conv-1/field-mapping', expect.objectContaining({ credentials: 'include', headers: expect.objectContaining({ 'Idempotency-Key': 'retry-key' }) }))
  })
  it.each([['attachment; filename="mappedconfig_20261010_1000_Base64.txt"', 'mappedconfig_20261010_1000_Base64.txt'], ["attachment; filename*=UTF-8''%E6%98%A0%E5%B0%84_Base64.txt", '映射_Base64.txt']])('keeps the server filename and releases the Blob URL (%s)', async (header, name) => {
    vi.mocked(fetch).mockResolvedValue(new Response('Base64 payload', { headers: { 'Content-Disposition': header } }))
    const file = await api.mappingDownload('map-1')
    expect(file.name).toBe(name)
    expect(fetch).toHaveBeenCalledWith('/api/v2/artifacts/map-1/download', expect.objectContaining({ credentials: 'include' }))
    const create = vi.fn(() => 'blob:download')
    const revoke = vi.fn()
    vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    saveDownload(file)
    expect(click).toHaveBeenCalledOnce()
    expect(revoke).toHaveBeenCalledWith('blob:download')
    expect(document.querySelector('a[download]')).not.toBeInTheDocument()
    click.mockRestore()
  })
  it('rejects a failed download without creating a Blob URL', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ error: { code: 'artifact_not_found', message: 'artifact_not_found' } }), { status: 404 }))
    await expect(api.mappingDownload('map-1')).rejects.toMatchObject({ status: 404, message: '结果不存在或当前身份无权查看，请返回会话。' })
  })
})

describe('Draft API wire contract', () => {
  it('preserves structured conflict details and expected revision for replacement', async () => {
    const details = { operation_key: 'row-key', proposal: { sub_rule_id: '0', source_path: 'src.ip', standard_field: '源地址', linked_sub_rule_ids: [] }, occupied_by: 'other.ip', candidates: { items: [] } }
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ error: { code: 'mapping_target_conflict', details } }), { status: 409 }))
    await expect(api.saveMapping('draft-1', 7, 'row-key', details.proposal)).rejects.toMatchObject({ code: 'mapping_target_conflict', status: 409, details })
    expect(fetch).toHaveBeenCalledWith('/api/v2/mapping-drafts/draft-1/operations/row-key', expect.objectContaining({ method: 'PATCH', headers: expect.objectContaining({ 'If-Match': '7' }), body: JSON.stringify(details.proposal) }))
  })
  it('sends apply idempotency and discard revision headers', async () => {
    await api.applyMappingDraft('draft-1', 4, 'durable-key')
    expect(fetch).toHaveBeenLastCalledWith('/api/v2/mapping-drafts/draft-1/apply', expect.objectContaining({ method: 'POST', headers: { 'If-Match': '4', 'Idempotency-Key': 'durable-key' } }))
    await api.discardMappingDraft('draft-1', 4)
    expect(fetch).toHaveBeenLastCalledWith('/api/v2/mapping-drafts/draft-1', expect.objectContaining({ method: 'DELETE', headers: { 'If-Match': '4' } }))
  })
})


it('shows six shared type columns and plain event names using actual projected values', async () => {
  vi.mocked(fetch).mockImplementation(() => Promise.resolve(reply(view({
    event_annotations: [
      { rule_name: 'audit', event_name: '审计事件', event_level: '信息', status: 'judged', threat_source_field: '不适用', threat_types: ['不适用'], type_source: '—（固定值）', type_values: ['数据库审计'] },
      { rule_name: 'login', event_name: '登录事件', event_level: '信息', status: 'judged', threat_source_field: '不适用', threat_types: ['不适用'], type_source: 'action', type_values: ['登录', '登出'] },
      { rule_name: 'legacy-audit', event_name: '资源监控', event_level: '信息', status: 'judged', threat_source_field: '不适用', threat_types: ['不适用'] },
      { rule_name: 'threat', event_name: '网络攻击', event_level: '提醒', status: 'judged', threat_source_field: 'attack_type', threat_types: ['暴力破解'] },
      { rule_name: 'unknown', event_name: '', event_level: 'unknown', status: 'uncertain', threat_source_field: '', threat_types: [] },
    ],
  }))))
  render(<MappingWorkspace {...props} />)
  fireEvent.click(await screen.findByText('事件名称标注 · 5 条'))
  const table = screen.getByRole('table', { name: '事件名称标注' })
  expect(within(table).getAllByRole('columnheader').map(cell => cell.textContent)).toEqual(['子规则', '事件名称', '事件级别', '判定来源', '威胁/操作类型', '状态'])
  const audit = within(table).getByText('audit').closest('tr')!
  expect(within(audit).getAllByRole('cell')[1]).toHaveTextContent(/^审计事件$/)
  expect(audit).toHaveTextContent('固定值数据库审计')
  expect(audit).not.toHaveTextContent('不适用')
  expect(within(table).getByText('login').closest('tr')).toHaveTextContent('日志字段 action登录、登出')
  expect(within(table).getByText('legacy-audit').closest('tr')).toHaveTextContent('未采集')
  expect(within(table).getByText('threat').closest('tr')).toHaveTextContent('日志字段 attack_type暴力破解')
  expect(within(table).getByText('unknown').closest('tr')).toHaveTextContent('未确定未生成')
  expect(within(table).queryByText('操作/审计事件')).not.toBeInTheDocument()
})
