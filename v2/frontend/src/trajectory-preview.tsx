/** Local visual QA route. It uses the same sanitized Run events as docs/design/workbench-redesign. */
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { api, type Conversation, type DiagnosticRun, type Run } from './api'
import { ConversationTimeline, type TimelineActions } from './ConversationTimeline'
import { TaskHintBar } from './VisualPrimitives'
import { TrajectoryLedger } from './TrajectoryLedger'
import runFixture from '../../../docs/design/workbench-redesign/run-fixture.json'
import './styles.css'
import './workbench.css'
import './trajectory-preview.css'

if (new URLSearchParams(location.search).has('dark')) document.documentElement.dataset.theme = 'dark'

const runId = 'a946359d-ebf7-49df-a2ee-04809fe6b98e'
const messageId = 'a16dca76-269e-4a5e-bca5-0b30041d42f3'
const runs = (runFixture as Run[]).map(run => ({ ...run, message_id: run.id === runId ? messageId : null }))
const accepted = runs.find(run => run.id === runId)!
const conversation: Conversation = { id: 'accepted-run', title: '安全日志字段映射', created_at: runs[0].queued_at!, updated_at: accepted.finished_at!, messages: [{ id: messageId, actor: 'user', content: '请根据这份安全日志完成标准字段映射，并保留可以人工检查的结果。' }], files: [], runs, artifacts: [] }
const calls = Array.from({ length: 14 }, (_, index) => ({ id: `call-${index + 1}`, run_id: runId, task_id: 'accepted-task', scope_id: 'step-f499265956fd1b3c7e4e014d', provider: '脱敏', model: '模型调用', operation: 'field_mapping', error_code: null, duration_ms: index === 0 ? 1625 : undefined }))
api.run = async id => runs.find(run => run.id === id)!
api.userDiagnosticRun = async () => ({ calls, artifacts: [], timeline: [] }) as unknown as DiagnosticRun
api.userDiagnosticCall = async (_run, call) => ({ ...calls.find(item => item.id === call)!, request: '按权限读取；预览不含原始模型内容', response: '按权限读取；预览不含原始模型内容' })

// Disposable authored example; not archived messages or a live backend session.
function ChatPreview() {
  const [draft, setDraft] = useState('')
  const [tab, setTab] = useState('conversation')
  const [stopped, setStopped] = useState(false)
  const [extraMessages, setExtraMessages] = useState<Conversation['messages']>([])
  const previewRun: Run = { id: 'preview-mapping', kind: 'field_mapping', status: stopped ? 'cancelled' : 'running', message_id: 'preview-user-1', events: [
    { sequence: 1, scope_type: 'step', scope_id: 'mapping', event_type: 'run_progress', status: 'running', summary: { operation: 'field_mapping', pipeline_stage: 'model_call', current_batch: 2, total_batches: 2 } }
  ] }
  const example: Conversation = { ...conversation, id: 'chat-design-example', files: [], artifacts: [], runs: [previewRun], messages: [
    { id: 'preview-user-1', actor: 'user', kind: 'text', content: '请根据这份安全日志完成标准字段映射，并保留可以人工检查的结果。', created_at: '2026-11-10T06:13:00Z' },
    { id: 'preview-assistant-1', actor: 'assistant', kind: 'text', content: '已收到。我会先检查日志内容，再提取字段并匹配标准字段。\n\n映射结果会保留来源字段，方便你逐项检查；需要人工判断的部分会单独标明。', created_at: '2026-11-10T06:13:01Z' },
    { id: 'preview-user-2', actor: 'user', kind: 'text', content: '无法确定的字段先保留，不要直接替我确认。', created_at: '2026-11-10T06:13:10Z' },
    { id: 'preview-assistant-2', actor: 'assistant', kind: 'text', content: '好的，无法确定的字段会保留为待检查项。\n\n文件校验已完成：84 行日志可以读取，共提取到 193 个字段。现在正在处理第 2 / 2 批标准字段映射，完成后会在这里展示结果。', run_id: previewRun.id, created_at: '2026-11-10T06:13:11Z' },
    ...extraMessages
  ] }
  api.run = async () => previewRun
  const noop = () => {}
  const actions: TimelineActions = { onOpenRun: () => setTab('trace'), onParseLog: noop, onFeatureField: noop, featureFields: {}, actionBusy: null, onMappingSource: noop, mappingForm: () => null, onOpenFieldChanges: noop, canOperate: false }
  const send = () => {
    if (!draft.trim()) return
    setExtraMessages([...extraMessages, { id: 'preview-local-' + extraMessages.length, actor: 'user', kind: 'text', content: draft, created_at: new Date().toISOString() }])
    setDraft('')
  }
  return <div className="app preview-shell preview-chat">
    <aside className="preview-sidebar"><strong>ToolWithAgent</strong><button disabled>＋ 新建会话</button><p className="active">工作台</p><p>任务记录</p><p>运行记录</p><small>最近会话</small><p className="active">安全日志字段映射</p><p>日志格式诊断</p></aside>
    <main><header className="preview-top"><strong>安全日志字段映射</strong><small>设计预览 · 示例文案</small></header>
      <nav className="workspace-tabs" aria-label="工作台视图"><button aria-selected={tab === 'conversation'} onClick={() => setTab('conversation')}>对话</button><button aria-selected={tab === 'trace'} onClick={() => setTab('trace')}>轨迹</button></nav>
      <div className="conversation-content" hidden={tab !== 'conversation'}><ConversationTimeline conversation={example} actions={actions} renderers={{ mappingSummary: () => null, businessCard: () => null, classificationCard: () => null }} /></div>
      {tab === 'trace' && <div className="preview-body"><TrajectoryLedger conversation={example} onOpen={noop} /></div>}
      <div className="composer-region" hidden={tab !== 'conversation'}><TaskHintBar state={stopped ? null : 'running'} title="标准字段映射" description="正在处理第 2 / 2 批字段"><button className="button-text" onClick={() => setTab('trace')}>查看执行详情</button><button className="button-text" onClick={() => setStopped(true)}>停止</button></TaskHintBar>
      <div className="composer"><textarea aria-label="消息内容" placeholder="描述要处理的日志、字段或规则…" value={draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send() } }} rows={2} /><div className="composer-toolbar"><div><label>上传用途<select aria-label="上传用途" defaultValue="primary"><option value="primary">日志或规则主数据</option><option value="enum_mapping">枚举映射附件</option></select></label><button className="attach-button" disabled>＋ 添加文件</button><span className="composer-hint">Enter 发送 · Shift+Enter 换行</span></div><button className="button-primary send-button" onClick={send} disabled={!draft.trim()}>发送</button></div></div>
      </div>
    </main>
  </div>
}

function Preview() {
  useEffect(() => {
    if (!new URLSearchParams(location.search).has('selected')) return
    const timer = setInterval(() => {
      const button = [...document.querySelectorAll<HTMLButtonElement>('.trajectory-event')].find(item => item.textContent?.includes('model_call'))
      if (button) { button.click(); clearInterval(timer) }
    }, 50)
    return () => clearInterval(timer)
  }, [])
  return <div className="app preview-shell"><aside className="preview-sidebar"><strong>ToolWithAgent</strong><button>＋ 新建会话</button><p className="active">工作台</p><p>任务记录</p><p>运行记录</p><small>最近会话</small><p>安全日志字段映射</p></aside><main><header className="preview-top"><strong>安全日志字段映射</strong><small>Run a946359d · 脱敏验收数据</small></header><nav className="preview-tabs">对话 <strong>轨迹</strong></nav><div className="preview-body"><TrajectoryLedger conversation={conversation} onOpen={() => {}} /></div></main></div>
}
createRoot(document.getElementById('root')!).render(new URLSearchParams(location.search).has('chat') ? <ChatPreview /> : <Preview />)
