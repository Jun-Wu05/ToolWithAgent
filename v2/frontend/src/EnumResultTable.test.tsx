import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { EnumResultCard, EnumResultTable } from './EnumResultTable'
import { api } from './api'
import type { BusinessArtifact } from './api'

vi.mock('./api', () => ({ api: { artifactContent: vi.fn() } }))

const enumArtifact: BusinessArtifact = { id: 'enum-1', run_id: 'r1', kind: 'enum_values', status: 'published', current: true }
const threatArtifact: BusinessArtifact = { id: 'threat-1', run_id: 'r1', kind: 'threat_mapping', status: 'published', current: true }
const many = (count: number) => Array.from({ length: count }, (_, index) => `值${index}`)

afterEach(() => { cleanup(); vi.resetAllMocks() })

it('renders zero, single and five enum rows with stable numbering and metadata', () => {
  render(<EnumResultTable kind="enum_values" content={{ field: 'alarm', values: [] }} />)
  expect(screen.getByText('没有可展示的结果。')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '查看全部' })).not.toBeInTheDocument()
  cleanup()
  render(<EnumResultTable kind="enum_values" content={{ field: 'alarm', values: ['允许'] }} />)
  expect(screen.getByText('01')).toBeInTheDocument()
  expect(screen.getByText('允许')).toBeInTheDocument()
  expect(screen.getByText(/显示前 1 条，共 1 条/)).toBeInTheDocument()
  expect(screen.getByText(/提取字段：alarm/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '查看全部' })).not.toBeInTheDocument()
})

it('paginates beyond fifty rows, searches the whole result and keeps page state while paging', async () => {
  render(<EnumResultTable kind="enum_values" content={{ field: 'alarm', values: many(51) }} />)
  expect(screen.getByText('显示前 5 条，共 51 条')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '查看全部' }))
  expect(await screen.findByText('值0')).toBeInTheDocument()
  expect(screen.getByText('1 / 2')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '下一页' }))
  expect(screen.getByText('值50')).toBeInTheDocument()
  expect(screen.getByText((_, element) => element?.tagName === 'SPAN' && element.textContent === '共 51 条')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('搜索全部结果'), { target: { value: '值5' } })
  // 搜索作用于全部 51 行而非当前页：仅「值5」「值50」命中，收敛为单页。
  await waitFor(() => expect(screen.getByText((_, element) => element?.tagName === 'SPAN' && element.textContent === '共 2 条')).toBeInTheDocument())
  expect(screen.getByText('值5')).toBeInTheDocument()
  expect(screen.getByText('值50')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '上一页' })).not.toBeInTheDocument()
  expect(screen.queryByText('没有匹配的结果。')).not.toBeInTheDocument()
})

it('keeps the original order and toggles header sorting with an accessible state', async () => {
  render(<EnumResultTable kind="enum_values" content={{ field: 'alarm', values: ['b值', 'a值', 'c值'] }} />)
  const header = screen.getByRole('button', { name: '按枚举值排序' })
  fireEvent.click(header)
  expect(screen.getByRole('columnheader', { name: /枚举值/ })).toHaveAttribute('aria-sort', 'ascending')
  expect(screen.getAllByRole('row')[1]).toHaveTextContent('a值')
  fireEvent.click(header)
  expect(screen.getByRole('columnheader', { name: /枚举值/ })).toHaveAttribute('aria-sort', 'descending')
  expect(screen.getAllByRole('row')[1]).toHaveTextContent('c值')
  fireEvent.click(header)
  expect(screen.getAllByRole('row')[1]).toHaveTextContent('b值')
})

it('preserves empty strings, zeros and long special characters without losing content', () => {
  render(<EnumResultTable kind="enum_values" content={{ field: '事件结果', values: ['', '0', '特殊"字符"<b>&amp;</b>' + '长'.repeat(120)] }} />)
  expect(screen.getByText('02')).toBeInTheDocument()
  expect(screen.getByText('特殊"字符"<b>&amp;</b>' + '长'.repeat(120))).toBeInTheDocument()
})

it('projects threat mapping rows into three columns with readable match types and folds the regex', () => {
  render(<EnumResultTable kind="enum_values" content={{ field: 'alarm', values: ['SQL注入'], regex: 'alarm=([^ ]+)' }} />)
  fireEvent.click(screen.getByText('提取正则'))
  expect(screen.getByText('alarm=([^ ]+)')).toBeInTheDocument()
  cleanup()
  render(<EnumResultTable kind="threat_mapping" content={{ source_field: '威胁类型', mappings: [
    { original_value: 'allow', mapped_value: '允许', mapping_type: 'EQUAL' },
    { original_value: '.*sql.*', mapped_value: 'SQL注入', mapping_type: 'REGULAR' },
  ] }} />)
  expect(screen.getByText('威胁类型映射结果')).toBeInTheDocument()
  expect(screen.getByText(/目标字段：威胁类型/)).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: '原始值' })).toBeInTheDocument()
  expect(screen.getByText('SQL注入')).toBeInTheDocument()
  expect(screen.getByText('正则')).toBeInTheDocument()
  expect(screen.getByText('相等')).toBeInTheDocument()
})

it('loads card content inline, retries after failure and marks stale results historical', async () => {
  vi.mocked(api.artifactContent).mockRejectedValueOnce(new Error('network'))
  const { rerender } = render(<EnumResultCard artifact={enumArtifact} identityKey="u1:c1" onOpen={vi.fn()} onDownload={vi.fn()} downloading={false} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('结果读取失败')
  vi.mocked(api.artifactContent).mockResolvedValue({ values: ['允许'] })
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await screen.findByText('允许')).toBeInTheDocument()
  rerender(<EnumResultCard artifact={{ ...enumArtifact, status: 'stale', current: false }} identityKey="u1:c1" onOpen={vi.fn()} onDownload={vi.fn()} downloading={false} />)
  expect(screen.getByText('历史结果，可查看和下载。')).toBeInTheDocument()
})

it('forwards open and download actions from the card buttons', async () => {
  vi.mocked(api.artifactContent).mockResolvedValue({ values: ['允许'] })
  const onOpen = vi.fn(); const onDownload = vi.fn()
  render(<EnumResultCard artifact={threatArtifact} identityKey="u1:c1" onOpen={onOpen} onDownload={onDownload} downloading error="下载失败" />)
  fireEvent.click(await screen.findByRole('button', { name: '查看产物' }))
  expect(onOpen).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: '下载结果' })).toBeDisabled()
  expect(screen.getByRole('alert')).toHaveTextContent('下载失败')
})
