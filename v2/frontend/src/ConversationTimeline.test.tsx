import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { buildTurns, ConversationTimeline, operationParamText } from './ConversationTimeline'
import type { Conversation } from './api'

const base = { id: 'c1', title: '会话', created_at: '', updated_at: '' }
const noopActions = {
  onOpenRun: vi.fn(), onParseLog: vi.fn(), onFeatureField: vi.fn(), featureFields: {}, actionBusy: null,
  onMappingSource: vi.fn(), mappingForm: () => null, onOpenFieldChanges: vi.fn(), canOperate: true,
}
const renderers = {
  mappingSummary: (artifact: { id: string }) => <p key={artifact.id}>映射摘要卡 {artifact.id}</p>,
  businessCard: (artifact: { id: string }) => <p key={artifact.id}>业务结果卡 {artifact.id}</p>,
  classificationCard: (artifact: { id: string }) => <p key={artifact.id}>解析结果卡 {artifact.id}</p>,
} as never

const linkedConversation: Conversation = {
  ...base,
  messages: [
    { id: 'm-file', actor: 'user', kind: 'file', content: '上传了主数据「demo.log」', payload: { action: 'file_upload', file_id: 'f1', name: 'demo.log', size: 2048, role: 'primary' } },
    { id: 'm-op', actor: 'user', kind: 'operation', content: '提交日志类型提取', payload: { action: 'log_parse', file_id: 'f1', name: 'demo.log', feature_field: 'level' } },
    { id: 'm-reply', actor: 'assistant', kind: 'text', content: '日志类型提取完成', run_id: 'run-parse' },
    { id: 'm-text', actor: 'user', kind: 'text', content: '继续导出规则' },
  ],
  files: [{ id: 'f1', name: 'demo.log', size: 2048, role: 'primary', parse_status: 'succeeded', mapping_eligible: true }],
  runs: [
    { id: 'run-parse', status: 'succeeded', kind: 'log_parse', message_id: 'm-op' },
    { id: 'run-legacy', status: 'failed', kind: 'file_ingest' },
  ],
  artifacts: [
    { id: 'art-class', run_id: 'run-parse', file_id: 'f1', kind: 'log_classification', status: 'published', result_message_id: 'm-reply', summary: {} } as never,
    { id: 'art-legacy', run_id: 'run-legacy', file_id: 'f-old', kind: 'config_export', status: 'stale' } as never,
  ],
  field_changes: [{ run_id: 'run-ghost', revision: 1, status: 'ready', apply_run_id: null, applied_artifact_id: null, undo_run_id: null, restored_artifact_id: null }],
}

it('builds turns from stable links and isolates unlinked history', () => {
  const { turns, unlinked } = buildTurns(linkedConversation)
  expect(turns.map(turn => turn.message.id)).toEqual(['m-file', 'm-op', 'm-reply', 'm-text'])
  expect(turns[1].runs.map(run => run.id)).toEqual(['run-parse'])
  expect(turns[2].artifacts.map(artifact => artifact.id)).toEqual(['art-class'])
  expect(unlinked.files).toEqual([])
  expect(unlinked.artifacts.map(artifact => artifact.id)).toEqual(['art-legacy'])
  expect(unlinked.fieldChanges.map(change => change.run_id)).toEqual(['run-ghost'])
  expect(unlinked.runs.map(run => run.id)).toEqual(['run-legacy'])
})

it('renders input records as attachment and operation cards without fabricated speech', () => {
  render(<ConversationTimeline conversation={linkedConversation} actions={noopActions} renderers={renderers} />)
  expect(screen.getByLabelText('输入附件：demo.log')).toBeInTheDocument()
  expect(screen.getByText('主数据 · 2.0 KB')).toBeInTheDocument()
  const operation = screen.getByLabelText('操作记录：日志类型提取')
  expect(operation).toHaveTextContent('操作')
  expect(operation).toHaveTextContent('分类特征字段 level')
  expect(screen.queryByText('提交日志类型提取')).not.toBeInTheDocument()
  expect(screen.getByText('解析结果卡 art-class')).toBeInTheDocument()
  const unlinked = screen.getByLabelText('历史独立操作')
  expect(unlinked).toHaveTextContent('3 项')
  fireEvent.click(screen.getByText(/历史独立操作/))
  expect(screen.getByText('业务结果卡 art-legacy')).toBeInTheDocument()
})

it('summarizes submitted parameters across upload, mapping and operations', () => {
  expect(operationParamText({ action: 'log_parse', feature_field: 'level' })).toBe('分类特征字段 level')
  expect(operationParamText({ action: 'field_mapping', product: '防火墙', log_vendor: '华为' })).toBe('产品 防火墙 · 厂商 华为')
  expect(operationParamText({ action: 'fill', step: { target_fields: ['威胁类型'], fill_kind: 'threat' } })).toContain('目标字段 威胁类型')
  expect(operationParamText({ action: 'enum_extract' })).toBe('')
})
