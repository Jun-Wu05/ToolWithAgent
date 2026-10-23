import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Identity } from './api'
import { StatusText } from './VisualPrimitives'
import { MappingDialog } from './MappingDialog'

const runKindName: Record<string, string> = { file_validation: '文件校验', field_change_apply: '应用字段变更', field_change_undo: '撤销字段变更', business_clear: '清空业务数据', user_request: '业务任务', business_operation: '业务处理', mapping_draft_apply: '应用映射修改', field_mapping: '标准字段映射', log_parse: '日志类型提取', log_knowledge_submit: '日志知识申请' }
const runKind = (kind: string) => runKindName[kind] || kind
const readableTime = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''
const auditActionName: Record<string, string> = { force_stop: '强停执行', cancel_queued: '取消排队' }
const auditAction = (action: string) => auditActionName[action] || action
const stoppable = new Set(['queued', 'running', 'waiting_confirmation'])

type Section = 'system' | 'runs' | 'providers' | 'users' | 'knowledge' | 'audit'
const sections: { id: Section; label: string }[] = [
  { id: 'system', label: '系统' }, { id: 'runs', label: '运行' }, { id: 'providers', label: 'Provider' },
  { id: 'users', label: '用户' }, { id: 'knowledge', label: '日志知识' }, { id: 'audit', label: '审计' },
]

type Props = { identity: Identity; identities: Identity[]; onSwitchIdentity: (userId: string) => void; theme: 'light' | 'dark'; onToggleTheme: () => void }

function useAsync<T>(loader: () => Promise<T>, deps: unknown[], enabled = true) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)
  const live = useRef(0)
  useEffect(() => {
    if (!enabled) return
    const version = ++live.current
    let active = true
    setLoading(true); setError('')
    loader().then(result => { if (active && version === live.current) setData(result) })
      .catch(caught => { if (active && version === live.current) setError(caught instanceof Error ? caught.message : '读取失败，请重试。') })
      .finally(() => { if (active && version === live.current) setLoading(false) })
    return () => { active = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reload, enabled])
  return { data, error, loading: loading && enabled, reload: () => setReload(value => value + 1) }
}

export function AdminConsole({ identity, identities, onSwitchIdentity, theme, onToggleTheme }: Props) {
  const [section, setSection] = useState<Section>('system')
  const [runStatus, setRunStatus] = useState('')
  const [runPage, setRunPage] = useState(1)
  const [auditPage, setAuditPage] = useState(1)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')
  const [stopTarget, setStopTarget] = useState<string | null>(null)
  const [stopReason, setStopReason] = useState('')
  const overview = useAsync(() => api.adminOverview(), [section], section === 'system')
  const runs = useAsync(() => api.adminRuns(runStatus, runPage), [section, runStatus, runPage], section === 'runs')
  const audit = useAsync(() => api.adminAuditEvents(auditPage), [section, auditPage], section === 'audit')
  useEffect(() => { setActionError('') }, [section])
  const cancelQueued = useCallback(async (runId: string) => {
    setActionBusy(runId); setActionError('')
    try {
      await api.adminCancelRun(runId)
      runs.reload(); overview.reload()
    } catch (caught) { setActionError(caught instanceof Error ? caught.message : '取消失败，请重试。') }
    finally { setActionBusy(null) }
  }, [runs, overview])
  const confirmStop = useCallback(async () => {
    if (!stopTarget) return
    const reason = stopReason.trim()
    if (!reason || actionBusy) return
    setActionBusy(stopTarget); setActionError('')
    try {
      await api.adminForceStop(stopTarget, reason)
      setStopTarget(null); setStopReason('')
      runs.reload(); overview.reload()
    } catch (caught) { setActionError(caught instanceof Error ? caught.message : '强停失败，请重试。') }
    finally { setActionBusy(null) }
  }, [stopTarget, stopReason, actionBusy, runs, overview])
  return <div className="app admin-app">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">T</span><span>ToolWithAgent <small>管理台</small></span></div>
      <nav aria-label="管理导航">{sections.map(item => <button key={item.id} className={'nav-item ' + (section === item.id ? 'selected' : '')} onClick={() => { setSection(item.id); if (item.id === 'runs') setRunPage(1); if (item.id === 'audit') setAuditPage(1) }}>{item.label}</button>)}</nav>
      <div className="identity">
        <div className="identity-head">
          <span className="avatar">{identity.display_name?.slice(0, 1) || '管'}</span>
          <span className="identity-name">{identity.display_name}<small>{identity.role}</small></span>
        </div>
        {identities.length > 1 && <select aria-label="开发身份切换" value={identity.id} onChange={event => onSwitchIdentity(event.target.value)}><option value={identity.id}>{identity.display_name} ({identity.role})</option>{identities.filter(item => item.id !== identity.id).map(item => <option key={item.id} value={item.id}>{item.display_name} ({item.role})</option>)}</select>}
      </div>
    </aside>
    <main className="workspace">
      <header className="workspace-header"><div><h1>管理台</h1><p>系统健康、运行队列、知识审核与审计记录</p></div><div className="header-actions"><button className="icon-button" aria-label={theme === 'light' ? '切换深色主题' : '切换浅色主题'} title={theme === 'light' ? '切换深色主题' : '切换浅色主题'} onClick={onToggleTheme}>{theme === 'light' ? '深色主题' : '浅色主题'}</button></div></header>
      {actionError && <div role="alert" className="feedback error"><span>{actionError}</span><button aria-label="关闭提示" onClick={() => setActionError('')}>关闭</button></div>}
      <div className="conversation-content"><div className="admin-sections">
        {section === 'system' && <section className="activity-section" aria-label="系统健康">
          <h2>系统健康</h2>
          {overview.loading && <p role="status">正在读取系统状态…</p>}
          {overview.error && <div className="mapping-error" role="alert"><span>{overview.error}</span><button className="button-secondary" onClick={overview.reload}>重试加载</button></div>}
          {overview.data && <>
            <div className="admin-metric-grid">
              {(['queued', 'running', 'waiting_confirmation', 'cancelling', 'succeeded', 'failed', 'cancelled'] as const).map(status => <div className="admin-metric" key={status}><strong>{overview.data!.runs[status] ?? 0}</strong><span>{({ queued: '排队中', running: '运行中', waiting_confirmation: '待确认', cancelling: '取消中', succeeded: '已完成', failed: '失败', cancelled: '已取消' } as Record<string, string>)[status]}</span></div>)}
            </div>
            <div className="admin-metric-grid">
              <div className="admin-metric"><strong>{overview.data.users}</strong><span>活跃用户</span></div>
              <div className="admin-metric"><strong>{overview.data.conversations}</strong><span>活跃会话</span></div>
              <div className="admin-metric"><strong>{overview.data.worker.lease_owner || '空闲'}</strong><span>Worker 租约 · 轮次 {overview.data.worker.epoch}</span></div>
            </div>
            <div className="mapping-actions"><button className="button-secondary" onClick={overview.reload} disabled={overview.loading}>刷新状态</button></div>
          </>}
        </section>}
        {section === 'runs' && <section className="activity-section" aria-label="运行队列">
          <h2>运行队列</h2>
          <div className="mapping-toolbar"><label>状态筛选<select aria-label="运行状态筛选" value={runStatus} onChange={event => { setRunStatus(event.target.value); setRunPage(1) }}><option value="">全部状态</option><option value="queued">排队中</option><option value="running">运行中</option><option value="waiting_confirmation">待确认</option><option value="succeeded">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option></select></label><button className="button-secondary" onClick={runs.reload} disabled={runs.loading}>刷新列表</button></div>
          {runs.loading && <p role="status">正在读取运行列表…</p>}
          {runs.error && <div className="mapping-error" role="alert"><span>{runs.error}</span><button className="button-secondary" onClick={runs.reload}>重试加载</button></div>}
          {runs.data && <>
            <div className="workbench-table-scroll"><table className="workbench-artifacts admin-runs-table"><caption className="sr-only">全部用户的执行记录</caption><thead><tr><th scope="col">执行</th><th scope="col">所有者</th><th scope="col">会话</th><th scope="col">状态</th><th scope="col">更新时间</th><th scope="col">操作</th></tr></thead><tbody>
              {runs.data.items.map(run => <tr key={run.id}><td>{runKind(run.kind)}<small className="mono">{run.id.slice(-8)}</small></td><td>{run.owner_name}</td><td>{run.conversation_title || '未命名会话'}</td><td><StatusText status={run.status} />{run.error_code && <small>{run.error_code}</small>}</td><td>{readableTime(run.updated_at)}</td><td className="admin-run-actions">{run.status === 'queued' && <button className="button-secondary" onClick={() => void cancelQueued(run.id)} disabled={!!actionBusy}>{actionBusy === run.id ? '取消中…' : '取消排队'}</button>}{stoppable.has(run.status) && <button className="button-secondary" onClick={() => { setStopTarget(run.id); setStopReason('') }} disabled={!!actionBusy}>强停</button>}</td></tr>)}
            </tbody></table>{!runs.data.items.length && <p className="workspace-empty">当前筛选没有执行记录。</p>}</div>
            {runs.data.total > runs.data.page_size && <footer className="mapping-pagination"><span>共 {runs.data.total} 条</span><div><button className="button-secondary" disabled={runs.data.page <= 1} onClick={() => setRunPage(page => page - 1)}>上一页</button><span>第 {runs.data.page} / {Math.ceil(runs.data.total / runs.data.page_size)} 页</span><button className="button-secondary" disabled={runs.data.page >= Math.ceil(runs.data.total / runs.data.page_size)} onClick={() => setRunPage(page => page + 1)}>下一页</button></div></footer>}
          </>}
        </section>}
        {section === 'audit' && <section className="activity-section" aria-label="审计记录">
          <h2>审计记录</h2>
          <div className="mapping-toolbar"><button className="button-secondary" onClick={audit.reload} disabled={audit.loading}>刷新记录</button></div>
          {audit.loading && <p role="status">正在读取审计记录…</p>}
          {audit.error && <div className="mapping-error" role="alert"><span>{audit.error}</span><button className="button-secondary" onClick={audit.reload}>重试加载</button></div>}
          {audit.data && <><div className="workbench-table-scroll"><table className="workbench-artifacts admin-audit-table"><caption className="sr-only">管理操作审计记录</caption><thead><tr><th scope="col">时间</th><th scope="col">操作者</th><th scope="col">动作</th><th scope="col">目标</th><th scope="col">原因</th><th scope="col">状态变化</th></tr></thead><tbody>
            {audit.data.items.map(event => <tr key={event.id}><td>{readableTime(event.created_at)}</td><td>{event.actor_name}</td><td>{auditAction(event.action)}</td><td className="mono">{event.target_type} · {event.target_id.slice(-8)}</td><td>{event.reason || '—'}</td><td>{event.before && event.after ? `${JSON.stringify(event.before)} → ${JSON.stringify(event.after)}` : '—'}</td></tr>)}
          </tbody></table>{!audit.data.items.length && <p className="workspace-empty">还没有管理操作记录。</p>}</div>
          {audit.data.total > audit.data.page_size && <footer className="mapping-pagination"><span>共 {audit.data.total} 条</span><div><button className="button-secondary" disabled={audit.data.page <= 1} onClick={() => setAuditPage(page => page - 1)}>上一页</button><span>第 {audit.data.page} / {Math.ceil(audit.data.total / audit.data.page_size)} 页</span><button className="button-secondary" disabled={audit.data.page >= Math.ceil(audit.data.total / audit.data.page_size)} onClick={() => setAuditPage(page => page + 1)}>下一页</button></div></footer>}</>}
        </section>}
        {(section === 'providers' || section === 'users' || section === 'knowledge') && <section className="activity-section" aria-label={sections.find(item => item.id === section)!.label}><h2>{sections.find(item => item.id === section)!.label}</h2><div className="empty-state compact"><p>该区域由后续切片交付（Provider 与密钥版本、用户角色、日志知识审核）。</p></div></section>}
      </div></div>
      {stopTarget && <MappingDialog title="确认强停执行" onClose={() => { setStopTarget(null); setStopReason('') }}>
        <p>强停会立即取消该执行并阻止迟到结果发布，已完成结果保留。必须填写原因，原因会写入审计记录。</p>
        <label className="admin-stop-reason">原因<textarea aria-label="强停原因" value={stopReason} onChange={event => setStopReason(event.target.value)} maxLength={1000} rows={3} placeholder="说明为什么需要强停" /></label>
        {actionError && <p className="mapping-error" role="alert">{actionError}</p>}
        <div className="mapping-actions"><button className="button-text" data-dialog-cancel onClick={() => { setStopTarget(null); setStopReason('') }} disabled={!!actionBusy}>取消</button><button className="button-text" onClick={() => void confirmStop()} disabled={!stopReason.trim() || !!actionBusy}>确认强停</button></div>
      </MappingDialog>}
    </main>
  </div>
}
