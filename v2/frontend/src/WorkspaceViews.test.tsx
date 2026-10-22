import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { compareSnapshots, ResultsWorkspace, TaskOverview } from './WorkspaceViews'
import { api, type Artifact, type Conversation } from './api'

vi.mock('./api', () => ({ api: { artifactContent: vi.fn(), run: vi.fn() } }))
const artifact = (id: string, current = true): Artifact => ({ id, kind: 'field_mapping', run_id: 'run-' + id, file_id: 'file', status: 'published', current, created_at: '2026-10-22T01:00:00Z', summary: { rule_count: 1, field_count: 2, matched_count: 1, unmatched_count: 1, parse_error_count: 0 } })
const versions = [artifact('old-snapshot', false), artifact('current-snapshot')]
const props = { artifacts: versions, active: true, mappingId: 'current-snapshot', mapping: <input aria-label="当前字段筛选" defaultValue="src_ip" />, targetId: null, blocked: false, onMapping: vi.fn(), onOpen: vi.fn(), onDownload: vi.fn() }
beforeEach(() => vi.mocked(api.artifactContent).mockImplementation(async id => id === 'old-snapshot' ? { config: { field: '旧值', deleted: true }, download_content: 'old-base64' } : { config: { field: '新值', added: true }, download_content: 'new-base64' }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('compares real JSON values and escapes ambiguous paths', () => {
  const result = compareSnapshots({ 'a/b': null, 'a~b': 1, removed: true }, { 'a/b': null, 'a~b': '1', added: [] })
  expect(result).toEqual(expect.arrayContaining([
    { path: '/a~1b', before: 'null', after: 'null', kind: '未变化' },
    { path: '/a~0b', before: '1', after: '"1"', kind: '修改' },
    { path: '/removed', before: 'true', after: undefined, kind: '删除' },
    { path: '/added', before: undefined, after: '[]', kind: '新增' },
  ]))
})

it('compares only actual snapshot IDs and retains the mapping workspace', async () => {
  render(<ResultsWorkspace {...props} />)
  fireEvent.change(screen.getByRole('textbox', { name: '当前字段筛选' }), { target: { value: 'device' } })
  fireEvent.click(screen.getByRole('button', { name: '比较真实版本' }))
  await screen.findByText('/config/field')
  expect(api.artifactContent).toHaveBeenCalledWith('old-snapshot')
  expect(api.artifactContent).toHaveBeenCalledWith('current-snapshot')
  expect(screen.getByText('新增')).toBeVisible()
  expect(screen.getByText('删除')).toBeVisible()
  expect(screen.queryByText('/download_content')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '返回结果内容' }))
  expect(screen.getByRole('textbox', { name: '当前字段筛选' })).toHaveValue('device')
})

it('keeps mapping filter input mounted across result categories', async () => {
  render(<ResultsWorkspace {...props} />)
  const input = screen.getByRole('textbox', { name: '当前字段筛选' })
  fireEvent.change(input, { target: { value: 'device' } })
  fireEvent.click(screen.getByRole('tab', { name: '解析规则' }))
  await screen.findByLabelText('解析规则内容')
  fireEvent.click(screen.getByRole('tab', { name: '字段映射' }))
  expect(screen.getByRole('textbox', { name: '当前字段筛选' })).toBe(input)
  expect(input).toHaveValue('device')
})

it('blocks changing version during a pending write and has no synthetic comparison', () => {
  render(<ResultsWorkspace {...props} artifacts={[versions[1]]} blocked />)
  expect(screen.getByRole('combobox', { name: '选择产物版本' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '比较真实版本' })).toBeDisabled()
  expect(screen.queryByText(/历史示意|v1|v2/)).not.toBeInTheDocument()
})

it('uses actual task data without declaring human review completed', () => {
  const conversation: Conversation = { id: 'conv', title: '真实任务', created_at: '', updated_at: '', files: [], messages: [], runs: [{ id: 'run', status: 'succeeded' }], artifacts: [versions[1]] }
  render(<TaskOverview conversation={conversation} drafts={[]} onResults={vi.fn()} onOpen={vi.fn()} onTrace={vi.fn()} onDownload={vi.fn()} />)
  expect(screen.getByText(/1 个未匹配字段/)).toBeVisible()
  expect(screen.queryByText('审查完成')).not.toBeInTheDocument()
})

it('does not display late content from a previous artifact', async () => {
  let finish!: (value: Record<string, unknown>) => void
  vi.mocked(api.artifactContent).mockImplementationOnce(() => new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ config: ['新产物'] })
  const view = render(<ResultsWorkspace {...props} />)
  fireEvent.click(screen.getByRole('tab', { name: '解析规则' }))
  await waitFor(() => expect(api.artifactContent).toHaveBeenCalled())
  view.rerender(<ResultsWorkspace {...props} artifacts={[artifact('other')]} mappingId="other" />)
  await screen.findByText(/新产物/)
  await act(async () => { finish({ config: ['旧敏感产物'] }) })
  expect(screen.queryByText(/旧敏感产物/)).not.toBeInTheDocument()
})
