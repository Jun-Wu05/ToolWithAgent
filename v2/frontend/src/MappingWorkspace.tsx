import { useEffect, useState } from 'react'
import { api, type FieldMappingArtifact, type MappingQuery, type MappingStatus, type MappingView } from './api'

const labels: Record<MappingStatus, string> = { matched: '映射成功', unmatched: '未匹配', parse_error: '解析异常' }
const statuses: MappingStatus[] = ['matched', 'unmatched', 'parse_error']
type Props = { artifact: FieldMappingArtifact; onBack: () => void; onDownload: () => void; downloading: boolean; downloadError: string }

export function MappingWorkspace({ artifact, onBack, onDownload, downloading, downloadError }: Props) {
  const [query, setQuery] = useState<MappingQuery>({ page: 1, q: '', status: '' })
  const [search, setSearch] = useState('')
  const [result, setResult] = useState<{ id: string; view: MappingView } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const data = result?.id === artifact.id ? result.view : null
  useEffect(() => {
    const controller = new AbortController()
    let live = true
    setLoading(true); setError('')
    api.mappingView(artifact.id, query, controller.signal).then(view => {
      if (live) setResult({ id: artifact.id, view })
    }).catch(caught => {
      if (live) setError(caught instanceof Error ? caught.message : '结果加载失败，请重试。')
    }).finally(() => { if (live) setLoading(false) })
    return () => { live = false; controller.abort() }
  }, [artifact.id, query, retry])
  const selectRule = (id: string) => setQuery({ ...query, sub_rule: id, page: 1 })
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  return <section className="mapping-workspace" aria-label="字段映射结果">
    <header className="mapping-header"><div><h2>字段映射结果</h2><p>{artifact.summary.rule_count} 条子规则，{artifact.summary.field_count} 个字段</p></div><div className="mapping-actions"><button className="button-secondary" onClick={onBack}>返回对话</button><button className="button-secondary" onClick={onDownload} disabled={downloading}>{downloading ? '下载中…' : '下载配置'}</button></div></header>
    {!artifact.current && <p className="mapping-warning" role="status">结果已过期，保留用于查看和下载。请从当前输入重新执行映射。</p>}
    {downloadError && <p className="mapping-error" role="alert">{downloadError}</p>}
    {data && <>
      {!!data.warnings?.length && <section className="mapping-business-warnings" aria-label="威胁类型处理提醒"><h3>威胁类型处理提醒</h3><ul>{data.warnings.map((warning, index) => <li key={warning.code + index}>{warning.message}</li>)}</ul></section>}
      <section className="mapping-annotations" aria-label="事件名称标注明细"><h3>事件名称标注</h3>{data.event_annotations?.length ? <div className="mapping-table-region annotation-table-region"><table className="annotation-table" aria-label="事件名称标注"><colgroup><col /><col /><col /><col /><col /><col /></colgroup><thead><tr><th scope="col">子规则</th><th scope="col">事件名称</th><th scope="col">事件级别</th><th scope="col">威胁类型来源</th><th scope="col">最终威胁类型</th><th scope="col">状态</th></tr></thead><tbody>{data.event_annotations.map((annotation, index) => <tr key={annotation.rule_name + index}><td>{annotation.rule_name || '未命名子规则'}</td><td>{annotation.event_name || '未生成'}</td><td>{!annotation.event_level || annotation.event_level === 'unknown' ? '未知' : annotation.event_level}</td><td className="mono">{annotation.threat_source_field || '未确定'}</td><td>{annotation.threat_types.length ? annotation.threat_types.join('、') : '未生成'}</td><td><span className={'mapping-badge ' + (annotation.status === 'judged' ? 'mapping-matched' : 'mapping-unmatched')}>{annotation.status === 'judged' ? '已判定' : '待人工确认'}</span></td></tr>)}</tbody></table></div> : <p className="mapping-hint">未生成事件名称标注。</p>}</section>
      <div className="mapping-rule-navigation"><div className="mapping-tabs" role="tablist" aria-label="子规则">{data.sub_rules.map(rule => <button role="tab" aria-selected={data.sub_rule_id === rule.id} className="mapping-tab" key={rule.id} onClick={() => selectRule(rule.id)} title={rule.name}>{rule.name}<small>{rule.field_count}</small></button>)}</div><label>全部子规则<select aria-label="全部子规则" value={data.sub_rule_id} onChange={event => selectRule(event.target.value)}>{data.sub_rules.map(rule => <option value={rule.id} key={rule.id}>{rule.name}</option>)}</select></label></div>
      <div className="mapping-toolbar"><form onSubmit={event => { event.preventDefault(); setQuery({ ...query, sub_rule: data.sub_rule_id, q: search.trim(), page: 1 }) }}><input type="search" aria-label="搜索字段或样例" placeholder="搜索字段或样例" maxLength={200} value={search} onChange={event => setSearch(event.target.value)} /><button className="button-secondary" type="submit">搜索</button></form><label>状态筛选<select aria-label="状态筛选" value={query.status} onChange={event => setQuery({ ...query, sub_rule: data.sub_rule_id, status: event.target.value, page: 1 })}><option value="">全部状态</option>{statuses.map(status => <option key={status} value={status}>{labels[status]}</option>)}</select></label></div>
      <p className="mapping-hint">搜索和筛选覆盖当前子规则的全部字段。样例位置表示原始日志条目序号。</p>
    </>}
    {loading && <p className="mapping-loading" role="status"><span className="loading-spinner" />正在加载字段…</p>}
    {error && <div className="mapping-error" role="alert"><span>{error}</span><button className="button-secondary" onClick={() => setRetry(retry + 1)}>重试加载</button></div>}
    {data && error && <p className="mapping-hint">以下保留上次成功加载的结果。</p>}
    {data && <div className="mapping-table-region" aria-busy={loading}><table className="mapping-table"><caption className="sr-only">当前子规则的字段映射</caption><thead><tr><th scope="col">原始字段</th><th scope="col">数据样例</th><th scope="col">映射的标准字段</th><th scope="col">匹配依据</th><th scope="col">状态</th></tr></thead>{statuses.map(status => {
      const rows = data.items.filter(row => row.status === status)
      return rows.length ? <tbody key={status}><tr className="mapping-group"><th colSpan={5} scope="rowgroup">{labels[status]}</th></tr>{rows.map(row => <tr key={row.source_path}><td><span className="mapping-source mono" title={row.source_path}>{row.source_path}</span></td><td>{row.samples.length ? <><ul className="mapping-samples">{row.samples.slice(0, 3).map((value, index) => <li key={index} title={value}>{value}</li>)}</ul>{row.expanded_samples.length > 0 && <details className="mapping-more"><summary>查看更多样例</summary><ol>{row.expanded_samples.slice(0, 20).map((sample, index) => <li key={index}><span className="mono">{sample.value}</span><small>{sample.line_number != null ? '日志条目 ' + sample.line_number : '配置样例（无日志位置）'}</small></li>)}</ol></details>}</> : <span className="mapping-hint">无非空样例</span>}</td><td><span className="mapping-value" title={row.standard_field}>{row.standard_field || '未映射'}</span></td><td><span className="mapping-evidence" title={row.evidence}>{row.evidence || '无匹配依据'}</span>{row.warning && <small className="mapping-warning">{row.warning}</small>}</td><td><span className={'mapping-badge mapping-' + row.status}>{labels[row.status]}</span></td></tr>)}</tbody> : null
    })}</table>{data.items.length === 0 && !loading && <p className="mapping-empty">没有符合条件的字段。</p>}</div>}
    {data && <footer className="mapping-pagination"><span>共 {data.total} 个字段 · 每页 {data.page_size} 个</span><div><button className="button-secondary" disabled={loading || data.page <= 1} onClick={() => setQuery({ ...query, sub_rule: data.sub_rule_id, page: data.page - 1 })}>上一页</button><span>第 {data.page} / {pages} 页</span><button className="button-secondary" disabled={loading || data.page >= pages} onClick={() => setQuery({ ...query, sub_rule: data.sub_rule_id, page: data.page + 1 })}>下一页</button></div></footer>}
  </section>
}
