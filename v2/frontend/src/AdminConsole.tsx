import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type AdminKnowledgeDetail, type Identity } from './api'
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
  const [knowledgeStatus, setKnowledgeStatus] = useState('')
  const [knowledgePage, setKnowledgePage] = useState(1)
  const [openKnowledge, setOpenKnowledge] = useState<number | null>(null)
  const [knowledgeDetail, setKnowledgeDetail] = useState<AdminKnowledgeDetail | null>(null)
  const [knowledgeDetailBusy, setKnowledgeDetailBusy] = useState(false)
  const [reviewReason, setReviewReason] = useState('')
  const [replacementRequired, setReplacementRequired] = useState(false)
  const overview = useAsync(() => api.adminOverview(), [section], section === 'system')
  const runs = useAsync(() => api.adminRuns(runStatus, runPage), [section, runStatus, runPage], section === 'runs')
  const audit = useAsync(() => api.adminAuditEvents(auditPage), [section, auditPage], section === 'audit')
  const knowledge = useAsync(() => api.adminKnowledge(knowledgeStatus, knowledgePage), [section, knowledgeStatus, knowledgePage], section === 'knowledge')
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
  const openKnowledgeDetail = useCallback(async (applicationId: number) => {
    setOpenKnowledge(applicationId); setKnowledgeDetail(null); setReviewReason(''); setReplacementRequired(false)
    setKnowledgeDetailBusy(true)
    try { setKnowledgeDetail(await api.adminKnowledgeDetail(applicationId)) }
    catch (caught) { setActionError(caught instanceof Error ? caught.message : '申请详情加载失败。'); setOpenKnowledge(null) }
    finally { setKnowledgeDetailBusy(false) }
  }, [])
  const reviewAction = useCallback(async (action: 'approve' | 'reject' | 'delete', applicationId: number) => {
    if (actionBusy) return
    const reason = reviewReason.trim()
    if (action === 'reject' && !reason) return
    if (action === 'approve' && replacementRequired && !reason) return
    setActionBusy('k' + applicationId); setActionError('')
    try {
      if (action === 'approve') {
        await api.adminKnowledgeApprove(applicationId, reason || undefined)
        setOpenKnowledge(null); setReviewReason(''); setReplacementRequired(false)
      } else if (action === 'reject') {
        await api.adminKnowledgeReject(applicationId, reason)
        setOpenKnowledge(null); setReviewReason('')
      } else {
        await api.adminKnowledgeDelete(applicationId)
        setOpenKnowledge(null)
      }
      knowledge.reload()
    } catch (caught) {
      const code = (caught as { code?: string }).code
      if (code === 'log_knowledge_replacement_reason_required') setReplacementRequired(true)
      setActionError(caught instanceof Error ? caught.message : '审核操作失败，请重试。')
    } finally { setActionBusy(null) }
  }, [actionBusy, reviewReason, replacementRequired, knowledge])
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
        {section === 'knowledge' && <section className="activity-section" aria-label="日志知识审核">
          <h2>日志知识审核</h2>
          <div className="mapping-toolbar"><label>状态筛选<select aria-label="知识申请状态筛选" value={knowledgeStatus} onChange={event => { setKnowledgeStatus(event.target.value); setKnowledgePage(1) }}><option value="">全部状态</option><option value="pending">待审核</option><option value="approved">已批准</option><option value="rejected">已拒绝</option></select></label><button className="button-secondary" onClick={knowledge.reload} disabled={knowledge.loading}>刷新列表</button></div>
          {knowledge.loading && <p role="status">正在读取知识申请…</p>}
          {knowledge.error && <div className="mapping-error" role="alert"><span>{knowledge.error}</span><button className="button-secondary" onClick={knowledge.reload}>重试加载</button></div>}
          {knowledge.data && <><div className="workbench-table-scroll"><table className="workbench-artifacts admin-knowledge-table"><caption className="sr-only">日志知识申请列表</caption><thead><tr><th scope="col">申请</th><th scope="col">格式 / 特征字段</th><th scope="col">提取器</th><th scope="col">状态</th><th scope="col">提交时间</th><th scope="col">操作</th></tr></thead><tbody>
            {knowledge.data.items.map(item => <tr key={item.application_id}><td><span className="mono">#{item.application_id}</span><small>{item.submitter}</small></td><td>{item.format_type}<small>{item.selection_mode === 'automatic' ? '自动识别' : item.feature_field || '未指定'}</small></td><td>{item.extractor_type === 'regex' ? '正则' : '字段路径'}</td><td><StatusText status={item.status === 'pending' ? 'queued' : item.status === 'approved' ? 'succeeded' : 'failed'} />{item.replaced_by_application_id && <small>已被 #{item.replaced_by_application_id} 替代</small>}{item.replaces_application_id && <small>替代 #{item.replaces_application_id}</small>}</td><td>{readableTime(item.created_at)}</td><td><button className="button-secondary" onClick={() => void openKnowledgeDetail(item.application_id)} disabled={knowledgeDetailBusy}>查看</button></td></tr>)}
          </tbody></table>{!knowledge.data.items.length && <p className="workspace-empty">当前筛选没有知识申请。</p>}</div>
          {knowledge.data.total > knowledge.data.page_size && <footer className="mapping-pagination"><span>共 {knowledge.data.total} 条</span><div><button className="button-secondary" disabled={knowledge.data.page <= 1} onClick={() => setKnowledgePage(page => page - 1)}>上一页</button><span>第 {knowledge.data.page} / {Math.ceil(knowledge.data.total / knowledge.data.page_size)} 页</span><button className="button-secondary" disabled={knowledge.data.page >= Math.ceil(knowledge.data.total / knowledge.data.page_size)} onClick={() => setKnowledgePage(page => page + 1)}>下一页</button></div></footer>}</>}
          {openKnowledge !== null && <MappingDialog title="日志知识申请详情" onClose={() => { setOpenKnowledge(null); setReviewReason(''); setReplacementRequired(false) }}>
            {knowledgeDetailBusy && <p role="status">正在加载申请详情…</p>}
            {!knowledgeDetailBusy && !knowledgeDetail && <p role="status">申请详情不可用，请关闭后重试。</p>}
            {knowledgeDetail && <div className="admin-knowledge-detail">
              <dl><dt>申请编号</dt><dd className="mono">#{knowledgeDetail.application_id}</dd><dt>状态</dt><dd>{({ pending: '待审核', approved: '已批准', rejected: '已拒绝' } as Record<string, string>)[knowledgeDetail.status] || knowledgeDetail.status}</dd><dt>格式</dt><dd>{knowledgeDetail.format_type} · 特征字段 {knowledgeDetail.selection_mode === 'automatic' ? '自动识别' : knowledgeDetail.feature_field || '未指定'}</dd><dt>配方版本</dt><dd>v{knowledgeDetail.recipe_version} · 结构 {knowledgeDetail.structure_hash.slice(0, 12)}</dd><dt>提取器</dt><dd>{knowledgeDetail.extractor_type === 'regex' ? '正则' : '字段路径'}</dd></dl>
              <pre className="admin-knowledge-spec">{JSON.stringify(knowledgeDetail.extractor_spec, null, 2)}</pre>
              {knowledgeDetail.submission_note && <p>提交说明：{knowledgeDetail.submission_note}</p>}
              {(knowledgeDetail.reviewer || knowledgeDetail.review_reason) && <p>审核记录：{knowledgeDetail.reviewer || '—'} · {knowledgeDetail.review_reason || '无理由'}</p>}
              {knowledgeDetail.replaces_application_id && <p>替代申请 #{knowledgeDetail.replaces_application_id}</p>}
              {knowledgeDetail.replaced_by_application_id && <p>已被申请 #{knowledgeDetail.replaced_by_application_id} 替代</p>}
              <details className="admin-knowledge-samples" open><summary>受限样例 · 最多 {knowledgeDetail.sample_count} 条</summary>{knowledgeDetail.samples.length ? knowledgeDetail.samples.map((sample, index) => <pre className="admin-knowledge-sample" key={index}>{sample}</pre>) : <p className="mapping-hint">没有保存样例。</p>}</details>
              {knowledgeDetail.status === 'pending' && <>
                {replacementRequired && <p className="mapping-warning" role="status">已存在同结构的已批准知识，批准将原子替代旧知识，必须填写理由。</p>}
                <label className="admin-stop-reason">审核理由{knowledgeDetail.status === 'pending' && '（批准普通情况可留空；拒绝必填）'}<textarea aria-label="审核理由" value={reviewReason} onChange={event => setReviewReason(event.target.value)} maxLength={1000} rows={3} placeholder="记录这次审核的依据或原因" /></label>
              </>}
              {actionError && <p className="mapping-error" role="alert">{actionError}</p>}
              <div className="mapping-actions">
                <button className="button-text" data-dialog-cancel onClick={() => { setOpenKnowledge(null); setReviewReason(''); setReplacementRequired(false) }} disabled={!!actionBusy}>关闭</button>
                {knowledgeDetail.status === 'pending' && <><button className="button-text" onClick={() => void reviewAction('approve', knowledgeDetail.application_id)} disabled={!!actionBusy || (replacementRequired && !reviewReason.trim())}>{actionBusy === 'k' + knowledgeDetail.application_id ? '处理中…' : replacementRequired ? '确认替代并批准' : '批准'}</button><button className="button-text" onClick={() => void reviewAction('reject', knowledgeDetail.application_id)} disabled={!!actionBusy || !reviewReason.trim()}>拒绝</button></>}
                {knowledgeDetail.status === 'rejected' && <button className="button-text" onClick={() => { if (window.confirm('删除已拒绝申请将级联清理样例，且不可恢复。确认删除？')) void reviewAction('delete', knowledgeDetail.application_id) }} disabled={!!actionBusy}>删除</button>}
              </div>
            </div>}
          </MappingDialog>}
        </section>}
        {(section === 'providers' || section === 'users') && <section className="activity-section" aria-label={sections.find(item => item.id === section)!.label}><h2>{sections.find(item => item.id === section)!.label}</h2><div className="empty-state compact"><p>该区域由后续切片交付（{section === 'providers' ? 'Provider 与密钥版本' : '用户角色管理'}）。</p></div></section>}
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
