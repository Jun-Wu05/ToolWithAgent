import { useEffect, useState } from 'react'
import { api, type HistoryPage, type UserRun, type UserTask } from './api'
import { fmtMs, StatusText } from './VisualPrimitives'
import { businessName } from './BusinessWorkspace'

type Kind = 'tasks' | 'runs'
type HistoryItem = UserTask | UserRun
const elapsed = (item: UserRun) => item.started_at && item.finished_at
  ? fmtMs(new Date(item.finished_at).getTime() - new Date(item.started_at).getTime()) : '—'
const filters = [
  ['', '全部'], ['queued', '排队中'], ['running', '运行中'],
  ['waiting_confirmation', '待确认'], ['succeeded', '已完成'],
  ['failed', '失败'], ['cancelling', '取消中'], ['cancelled', '已取消'],
] as const

export function UserHistory({ kind, onOpen }: { kind: Kind; onOpen: (conversationId: string, runId: string | null, messageId: string | null) => void }) {
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [result, setResult] = useState<HistoryPage<HistoryItem> | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let live = true
    setLoading(true); setError('')
    const request = kind === 'tasks' ? api.userTasks(status, page) : api.userRuns(status, page)
    void request.then(value => { if (live) setResult(value) }).catch(caught => {
      if (live) setError(caught instanceof Error ? caught.message : '历史记录加载失败。')
    }).finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [kind, status, page])
  return <section className="activity-section" aria-label={kind === 'tasks' ? '我的任务' : '我的执行'}>
    <h2>{kind === 'tasks' ? '我的任务' : '我的执行'}</h2>
    <p>跨会话查看历史，选择记录可返回原会话并打开执行详情。</p>
    <div className="status-filters" role="group" aria-label="历史状态">{filters.map(([value, label]) =>
      <button key={value} type="button" className="focus-ring" aria-pressed={status === value} onClick={() => { setStatus(value); setPage(1) }}>{label}</button>
    )}</div>
    {error && <p role="alert" className="mapping-error">{error}</p>}
    {loading ? <p role="status">正在加载…</p> : result?.items.length ? <>
      <div className="history-list">{result.items.map(item => {
        const runId = kind === 'runs' ? item.id : (item as UserTask).current_run_id
        return <article className="result-card row-hover" key={item.id}>
          <strong>{item.conversation_title || '未命名会话'}</strong>
          <p>{businessName(kind === 'tasks' ? (item as UserTask).type : (item as UserRun).kind || '')} · <StatusText status={item.status} /></p>
          <p>更新于 {new Date(item.updated_at || item.created_at || '').toLocaleString('zh-CN')}{kind === 'runs' && <> · 耗时 <span className="num">{elapsed(item as UserRun)}</span></>}</p>
          <button className="button-secondary" onClick={() => onOpen(item.conversation_id, runId, item.message_id || null)}>回到原会话{runId ? '并查看执行' : ''}</button>
        </article>
      })}</div>
      <div className="mapping-actions"><button className="button-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} 页 · 共 {result.total} 条</span><button className="button-secondary" disabled={page * result.page_size >= result.total} onClick={() => setPage(page + 1)}>下一页</button></div>
    </> : <p>当前筛选下没有{kind === 'tasks' ? '任务' : '执行'}记录。</p>}
  </section>
}
