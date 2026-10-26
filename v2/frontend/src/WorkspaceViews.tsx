import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Artifact, type Conversation, type MappingDraftSummary, type Run } from './api'
import { ArtifactValues, businessName, RunProgress } from './BusinessWorkspace'
import { CopyButton, StatusText } from './VisualPrimitives'

export type WorkspaceTab = 'conversation' | 'overview' | 'results' | 'trace'
const date = (value?: string) => value ? new Date(value).toLocaleString('zh-CN') : '时间未记录'
const current = (artifact: Artifact) => artifact.status === 'published' && (!('current' in artifact) || artifact.current)
const versionName = (artifact: Artifact) => `${current(artifact) ? '当前' : '历史'} · ${date(artifact.created_at)} · ${artifact.id.slice(-8)}`

function ArtifactTable({ artifacts, onOpen, onDownload }: { artifacts: Artifact[]; onOpen: (artifact: Artifact) => void; onDownload: (id: string) => void }) {
  return <div className="workbench-table-scroll"><table className="workbench-artifacts"><thead><tr><th>产物</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>{artifacts.map(artifact => <tr key={artifact.id}><td><button className="button-text" onClick={() => onOpen(artifact)}>{businessName(artifact.kind)}结果</button></td><td><code>{artifact.id.slice(-8)}</code><small>{date(artifact.created_at)}</small></td><td>{artifact.status === 'corrupt' ? '不可用' : current(artifact) ? '当前产物' : '历史产物'}</td><td><button className="button-text" aria-label={'下载产物 ' + artifact.id} onClick={() => onDownload(artifact.id)}>下载</button></td></tr>)}</tbody></table>{!artifacts.length && <p className="workspace-empty">还没有可查看的产物。执行任务后会在这里显示。</p>}</div>
}

export function TaskFacts({ conversation, drafts }: { conversation: Conversation; drafts: MappingDraftSummary[] }) {
  const artifacts = conversation.artifacts || []
  const changes = drafts.reduce((sum, draft) => sum + draft.changed_count, 0)
  return <><h3>任务信息</h3><dl><dt>会话</dt><dd>{conversation.title}</dd><dt>输入文件</dt><dd>{conversation.files.filter(file => file.active !== false).map(file => file.name).join('、') || '尚未上传'}</dd><dt>已发布产物</dt><dd>{artifacts.filter(current).length} 份</dd><dt>未应用草稿</dt><dd>{drafts.length ? `${drafts.length} 份 · ${changes} 处修改` : '无'}</dd><dt>最近更新</dt><dd>{date(conversation.updated_at)}</dd></dl><p className="mapping-hint">人工确认仅依据真实待确认事项显示，不从未匹配数量推断审核结论。</p></>
}

export function TaskOverview({ conversation, drafts, onOpen, onTrace, onDownload, onConversation, onRun, onDraft, contextOpen = false }: { conversation: Conversation; drafts: MappingDraftSummary[]; onOpen: (artifact: Artifact) => void; onTrace: () => void; onDownload: (id: string) => void; onConversation: () => void; onRun: (id: string) => void; onDraft: (draft: MappingDraftSummary) => void; contextOpen?: boolean }) {
  const artifacts = conversation.artifacts || []
  const latest = conversation.runs.at(-1)
  const mapping = [...artifacts].reverse().find(item => item.kind === 'field_mapping' && current(item))
  const waiting = conversation.runs.some(run => run.status === 'waiting_confirmation')
  const changes = drafts.reduce((sum, draft) => sum + draft.changed_count, 0)
  const draft = drafts[0]
  const next = waiting
    ? { title: '处理待确认方案', description: '返回对话检查执行方案，确认后继续。', label: '处理待确认方案', action: onConversation }
    : draft
      ? { title: '检查并应用草稿', description: `${changes} 处已保存修改尚未应用。`, label: '查看结果与草稿', action: () => onDraft(draft) }
      : latest?.status === 'failed'
        ? { title: '查看失败原因', description: '检查本次执行详情后决定是否重试。', label: '查看失败原因', action: () => onRun(latest.id) }
        : mapping
          ? { title: '检查字段映射', description: mapping.kind === 'field_mapping' ? `${mapping.summary.unmatched_count} 个未匹配字段；映射状态不代表人工审查状态。` : '', label: '查看结果与草稿', action: () => onOpen(mapping) }
          : latest
            ? { title: '查看当前进展', description: '查看真实执行状态与关联产物。', label: '查看执行轨迹', action: onTrace }
            : { title: '开始当前任务', description: '返回对话上传文件或描述要处理的内容。', label: '返回对话', action: onConversation }
  return <section className={'task-overview' + (contextOpen ? ' task-context-open' : '')} aria-label="任务概览"><div className="task-overview-grid"><article>
    <header><h2>{waiting ? '执行需要你的确认' : latest?.status === 'failed' ? '查看失败原因，继续处理任务' : artifacts.length ? '检查产物，继续迭代' : '从对话开始当前任务'}</h2><p>任务执行、已发布产物和未应用的草稿分别保留，便于检查与继续处理。</p></header>
    <section className="workspace-next-action"><div><strong>下一步：{next.title}</strong><p>{next.description}</p></div><button className="button-secondary" onClick={next.action}>{next.label}</button></section>
    <h3>本任务产物</h3><ArtifactTable artifacts={artifacts} onOpen={onOpen} onDownload={onDownload} />
    <div className="workspace-section-heading"><h3>处理记录</h3><button className="button-text" onClick={onTrace}>查看完整轨迹</button></div>
    {conversation.runs.slice(-5).reverse().map(run => <div className="overview-run" key={run.id}><time>{date(run.created_at)}</time><span>{businessName(run.kind || '')}</span><StatusText status={run.status} /></div>)}
  </article><aside className="workspace-task-facts"><TaskFacts conversation={conversation} drafts={drafts} /></aside></div></section>
}

type Flat = Map<string, string>
function flatten(value: unknown, path = '', result: Flat = new Map()): Flat {
  if (value && typeof value === 'object' && Object.keys(value).length) {
    for (const [key, item] of Object.entries(value)) flatten(item, path + '/' + key.replaceAll('~', '~0').replaceAll('/', '~1'), result)
  } else result.set(path || '/', JSON.stringify(value) ?? '未定义')
  return result
}
export function compareSnapshots(before: unknown, after: unknown) {
  const left = flatten(before), right = flatten(after)
  return [...new Set([...left.keys(), ...right.keys()])].map(path => ({ path, before: left.get(path), after: right.get(path), kind: !left.has(path) ? '新增' : !right.has(path) ? '删除' : left.get(path) === right.get(path) ? '未变化' : '修改' }))
}

function SnapshotComparison({ before, after }: { before: Artifact; after: Artifact }) {
  const [result, setResult] = useState<ReturnType<typeof compareSnapshots> | null>(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let live = true
    setResult(null); setError(''); setPage(1)
    Promise.all([api.artifactContent(before.id), api.artifactContent(after.id)]).then(([left, right]) => { if (live) setResult(compareSnapshots(Object.fromEntries(Object.entries(left).filter(([key]) => key !== 'download_content')), Object.fromEntries(Object.entries(right).filter(([key]) => key !== 'download_content')))) }).catch(caught => { if (live) setError(caught instanceof Error ? caught.message : '版本内容读取失败。') })
    return () => { live = false }
  }, [before.id, after.id, retry])
  const changes = result?.filter(row => row.kind !== '未变化') || []
  return <section className="snapshot-comparison" aria-label="真实版本差异"><h3>版本内容比较</h3><p><code>{before.id.slice(-8)}</code> → <code>{after.id.slice(-8)}</code> · 按真实内容的 JSON 路径比较（不重复比较下载编码）</p>{!result && !error && <p role="status">正在读取版本快照…</p>}{error && <p className="mapping-error" role="alert">{error}<button className="button-text" onClick={() => setRetry(retry + 1)}>重试比较</button></p>}{result && <><p>{changes.length} 项变化 · {result.length - changes.length} 项未变化</p><div className="workbench-table-scroll"><table><thead><tr><th>变化</th><th>内容路径</th><th>修改前</th><th>修改后</th></tr></thead><tbody>{changes.slice((page - 1) * 30, page * 30).map(row => <tr key={row.path}><td><span className="snapshot-kind" data-kind={row.kind}>{row.kind}</span></td><td><code>{row.path}</code></td><td><code>{row.before ?? '—'}</code></td><td><code>{row.after ?? '—'}</code></td></tr>)}</tbody></table></div>{!changes.length && <p>两份产物的内容相同。</p>}{changes.length > 30 && <div className="mapping-pagination"><button className="button-secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>上一页差异</button><span>{page} / {Math.ceil(changes.length / 30)}</span><button className="button-secondary" disabled={page * 30 >= changes.length} onClick={() => setPage(page + 1)}>下一页差异</button></div>}</>}</section>
}

function ArtifactPreview({ artifact, rules }: { artifact: Artifact; rules: boolean }) {
  const [content, setContent] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let live = true
    setContent(null); setError('')
    api.artifactContent(artifact.id).then(result => { if (live) setContent(result) }).catch(caught => { if (live) setError(caught instanceof Error ? caught.message : '产物读取失败。') })
    return () => { live = false }
  }, [artifact.id, retry])
  return <section aria-label={rules ? '解析规则内容' : '日志分类内容'}>{error && <p className="mapping-error" role="alert">{error}<button className="button-text" onClick={() => setRetry(retry + 1)}>重试读取产物</button></p>}{!error && !content && <p role="status">正在读取真实产物…</p>}{content && (rules ? <pre className="artifact-content">{JSON.stringify(content.config ?? content, null, 2)}</pre> : <ArtifactValues artifact={artifact} content={content} />)}</section>
}

export function ResultsWorkspace({ artifacts, active, mappingId, mapping, targetId, targetToken = 0, blocked, onMapping, onOpen, onDownload }: { artifacts: Artifact[]; active: boolean; mappingId: string | null; mapping: ReactNode; targetId: string | null; targetToken?: number; blocked: boolean; onMapping: (id: string) => void; onOpen: (artifact: Artifact) => void; onDownload: (id: string) => void }) {
  const [kind, setKind] = useState<'classification' | 'mapping' | 'rules'>('mapping')
  const [selected, setSelected] = useState<Record<string, string>>({})
  const [baseline, setBaseline] = useState('')
  const [compare, setCompare] = useState(false)
  const targetKind = artifacts.find(item => item.id === targetId)?.kind
  useEffect(() => {
    if (!targetId || !targetKind) return
    const next = targetKind === 'log_classification' ? 'classification' : 'mapping'
    setKind(next); setSelected(values => ({ ...values, [next]: targetId })); setCompare(false)
  }, [targetId, targetKind, targetToken])
  const versions = artifacts.filter(item => kind === 'classification' ? item.kind === 'log_classification' : kind === 'mapping' ? item.kind === 'field_mapping' : item.kind === 'field_mapping' || item.kind === 'log_classification').slice().reverse()
  const artifact = versions.find(item => item.id === (kind === 'mapping' ? mappingId : selected[kind])) || versions[0]
  const previous = versions.find(item => item.id === baseline && item.id !== artifact?.id && item.kind === artifact?.kind) || versions.find(item => item.id !== artifact?.id && item.kind === artifact?.kind)
  const artifactId = artifact?.id
  useEffect(() => { if (active && kind === 'mapping' && artifactId && mappingId !== artifactId && !blocked) onMapping(artifactId) }, [active, kind, artifactId, mappingId, blocked, onMapping])
  const others = artifacts.filter(item => !['field_mapping', 'log_classification'].includes(item.kind))
  return <section className="results-workspace" aria-label="结果与版本"><header className="workspace-section-heading"><div><h2>结果与版本</h2><p>产物与已保存草稿分开管理，历史内容保持只读。</p></div>{artifact && <div className="mapping-actions"><label><span className="sr-only">选择产物版本</span><select aria-label="选择产物版本" disabled={blocked} value={artifact.id} onChange={event => { setCompare(false); if (kind === 'mapping') onMapping(event.target.value); else setSelected(values => ({ ...values, [kind]: event.target.value })) }}>{versions.map(item => <option key={item.id} value={item.id}>{versionName(item)}</option>)}</select></label><button className="button-secondary" disabled={!previous || blocked} onClick={() => setCompare(!compare)}>{compare ? '返回结果内容' : '比较真实版本'}</button></div>}</header>
    <div className="result-kind-tabs" role="tablist" aria-label="结果类型">{([['classification', '日志分类'], ['mapping', '字段映射'], ['rules', '解析规则']] as const).map(([id, label]) => <button role="tab" key={id} aria-selected={kind === id} disabled={blocked} onClick={() => { setKind(id); setCompare(false) }}>{label}</button>)}</div>
    <div hidden={kind !== 'mapping' || compare}>{mapping}</div>
    {!artifact ? <p className="workspace-empty">当前会话还没有这类产物。完成任务后可在这里查看。</p> : compare && previous ? <><label className="comparison-baseline">对比基准<select aria-label="选择对比基准" value={previous.id} onChange={event => setBaseline(event.target.value)}>{versions.filter(item => item.id !== artifact.id && item.kind === artifact.kind).map(item => <option key={item.id} value={item.id}>{versionName(item)}</option>)}</select></label><SnapshotComparison key={previous.id + ':' + artifact.id} before={previous} after={artifact} /></> : <>
      {active && kind !== 'mapping' && <><div className="workspace-section-heading"><span>{versionName(artifact)}</span><button className="button-secondary" onClick={() => onDownload(artifact.id)}>下载产物</button></div><ArtifactPreview key={artifact.id + ':' + kind} artifact={artifact} rules={kind === 'rules'} /></>}
    </>}
    {others.length > 0 && <details className="other-artifacts"><summary>其他业务产物 · {others.length} 份</summary><ArtifactTable artifacts={others} onOpen={onOpen} onDownload={onDownload} /></details>}
  </section>
}

function TraceRun({ run, artifacts, onOpen, onDetails }: { run: Run; artifacts: Artifact[]; onOpen: (artifact: Artifact) => void; onDetails: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    if (!expanded) return
    let live = true
    setError(''); setDetail(null)
    api.run(run.id).then(value => { if (live) setDetail(value) }).catch(caught => { if (live) setError(caught instanceof Error ? caught.message : '执行详情读取失败。') })
    return () => { live = false }
  }, [run.id, run.updated_at, expanded, retry])
  const value = detail || run
  const inputs = JSON.stringify({ message_id: value.message_id ?? null, file_id: value.file_id ?? null }, null, 2)
  const outputs = artifacts.filter(item => item.run_id === run.id)
  const outputReferences = JSON.stringify(outputs.map(item => ({ id: item.id, kind: item.kind, status: item.status })), null, 2)
  return <details className={'workspace-trace-run trace-' + run.status} open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}><summary><strong>{businessName(run.kind || run.type || '')}</strong><StatusText status={run.status} /><time>{date(run.created_at)}</time></summary><div className="workspace-trace-detail">{error && <p className="mapping-error" role="alert">{error}<button className="button-text" onClick={() => setRetry(retry + 1)}>重试读取详情</button></p>}<dl><dt>执行标识</dt><dd><code>{run.id}</code></dd><dt>任务标识</dt><dd><code>{value.task_id || '未记录'}</code></dd><dt>执行状态</dt><dd><StatusText status={value.status} /></dd>{value.error_code && <><dt>错误代码</dt><dd><code>{value.error_code}</code></dd></>}{value.error_message && <><dt>原因</dt><dd>{value.error_message}</dd></>}</dl><RunProgress run={value} /><details><summary>输入引用</summary><pre>{inputs}</pre><CopyButton text={inputs} label="复制输入引用" /></details><details><summary>输出产物</summary>{outputs.length ? outputs.map(item => <p key={item.id}><button className="button-text" onClick={() => onOpen(item)}>查看{businessName(item.kind)}产物</button></p>) : <p>本次执行没有已发布产物。</p>}<pre>{outputReferences}</pre><CopyButton text={outputReferences} label="复制输出引用" /></details><details><summary>执行记录 JSON</summary><pre>{JSON.stringify(value, null, 2)}</pre></details><div className="mapping-actions"><CopyButton text={JSON.stringify(value, null, 2)} label="复制执行记录" /><button className="button-text" onClick={() => onDetails(run.id)}>查看完整执行详情</button></div></div></details>
}

export function ExecutionTrace({ conversation, onOpen, onDetails }: { conversation: Conversation; onOpen: (artifact: Artifact) => void; onDetails: (id: string) => void }) {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const search = query.toLowerCase().trim()
  const runs = conversation.runs.filter(run => (!status || run.status === status) && `${businessName(run.kind || '')} ${run.id} ${run.error_message || ''}`.toLowerCase().includes(search))
  const groups = new Map<string, Run[]>()
  for (const run of runs) { const key = run.message_id || run.id; groups.set(key, [...(groups.get(key) || []), run]) }
  const heading = useRef<HTMLHeadingElement>(null)
  return <section className="execution-workspace" aria-label="执行轨迹"><header className="workspace-section-heading"><div><h2 ref={heading}>执行轨迹</h2><p>{conversation.runs.length} 次真实执行 · 展开查看记录与关联产物</p></div><div className="mapping-actions"><input aria-label="搜索执行记录" placeholder="搜索执行或错误" value={query} onChange={event => setQuery(event.target.value)} /><select aria-label="筛选执行状态" value={status} onChange={event => setStatus(event.target.value)}><option value="">全部状态</option><option value="failed">失败</option><option value="waiting_confirmation">待人工确认</option><option value="running">运行中</option><option value="succeeded">已完成</option><option value="cancelled">已取消</option></select></div></header>{[...groups].map(([id, items], index) => <section className="workspace-trace-group" key={id}><header><span>第 {index + 1} 组</span><p>{conversation.messages.find(message => message.id === id)?.content || '文件或业务执行'}</p></header>{items.map(run => <TraceRun key={run.id} run={run} artifacts={conversation.artifacts || []} onOpen={onOpen} onDetails={onDetails} />)}</section>)}{!runs.length && <p className="workspace-empty">没有符合条件的执行记录。</p>}</section>
}
