import { useEffect, useState } from 'react'
import { api, type BusinessArtifact } from './api'
import './enum-result-table.css'

type Row = string[]

export function EnumResultTable({ kind, content }: { kind: 'enum_values' | 'threat_mapping'; content: Record<string, unknown> }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<{ index: number; desc: boolean } | null>(null)
  const values = kind === 'enum_values' && Array.isArray(content.values) ? content.values : []
  const mappings = kind === 'threat_mapping' && Array.isArray(content.mappings) ? content.mappings : []
  const headers = kind === 'enum_values' ? ['序号', '枚举值'] : ['原始值', '标准威胁类型', '映射方式']
  const rows: Row[] = kind === 'enum_values'
    ? values.map((value, index) => [String(index + 1).padStart(2, '0'), String(value ?? '')])
    : mappings.map(value => {
      const row = value && typeof value === 'object' ? value as Record<string, unknown> : {}
      return [String(row.original_value ?? ''), String(row.mapped_value ?? ''), row.mapping_type === 'REGULAR' ? '正则' : '相等']
    })
  const filtered = open && query ? rows.filter(row => row.some(value => value.toLocaleLowerCase().includes(query.toLocaleLowerCase()))) : rows
  const ordered = sort === null ? filtered : [...filtered].sort((a, b) => (sort.desc ? -1 : 1) * a[sort.index].localeCompare(b[sort.index], 'zh-CN', { numeric: true }))
  const count = open ? ordered.length : Math.min(5, ordered.length)
  const lastPage = Math.max(1, Math.ceil(count / 50))
  const safePage = Math.min(page, lastPage)
  const visible = open ? ordered.slice((safePage - 1) * 50, safePage * 50) : ordered.slice(0, 5)
  return <section className="enum-result" aria-label={kind === 'enum_values' ? '枚举提取结果' : '威胁类型映射结果'}>
    <div className="enum-result-heading"><strong>{kind === 'enum_values' ? '枚举提取结果' : '威胁类型映射结果'}</strong><span>● 已完成</span></div>
    <p className="enum-result-meta">{kind === 'enum_values' ? `提取字段：${String(content.field ?? '未指定')}` : `目标字段：${String(content.source_field ?? '威胁类型')}`} · 共 {rows.length} 条</p>
    {open && <input aria-label="搜索全部结果" placeholder="搜索全部结果" value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} />}
    <div className="enum-result-scroll"><table><thead><tr>{headers.map((header, index) => <th scope="col" aria-sort={sort?.index === index ? (sort.desc ? 'descending' : 'ascending') : 'none'} key={header}><button type="button" onClick={() => { setSort(sort?.index === index ? (sort.desc ? null : { index, desc: true }) : { index, desc: false }); setPage(1) }} aria-label={'按' + header + '排序'}>{header}{sort?.index === index ? (sort.desc ? ' ↓' : ' ↑') : ''}</button></th>)}</tr></thead><tbody>{visible.map((row, index) => <tr key={(safePage - 1) * 50 + index}>{row.map((value, cell) => <td key={cell}>{value}</td>)}</tr>)}</tbody></table></div>
    {rows.length === 0 && <p>没有可展示的结果。</p>}
    {open && ordered.length === 0 && rows.length > 0 && <p>没有匹配的结果。</p>}
    <div className="enum-result-footer"><span>{open ? `共 ${ordered.length} 条` : `显示前 ${count} 条，共 ${rows.length} 条`}</span><div>{open && lastPage > 1 && <><button type="button" className="button-text" disabled={safePage === 1} onClick={() => setPage(safePage - 1)}>上一页</button><span>{safePage} / {lastPage}</span><button type="button" className="button-text" disabled={safePage === lastPage} onClick={() => setPage(safePage + 1)}>下一页</button></>}{rows.length > 5 && <button type="button" className="button-text" onClick={() => { setOpen(!open); setPage(1) }}>{open ? '收起' : '查看全部'}</button>}</div></div>
    {kind === 'enum_values' && typeof content.regex === 'string' && <details><summary>提取正则</summary><pre>{content.regex}</pre></details>}
  </section>
}

export function EnumResultCard({ artifact, identityKey, onOpen, onDownload, downloading, error }: { artifact: BusinessArtifact; identityKey: string; onOpen: () => void; onDownload: () => void; downloading: boolean; error?: string }) {
  const [content, setContent] = useState<Record<string, unknown> | null>(null)
  const [loadError, setLoadError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let live = true
    api.artifactContent(artifact.id).then(value => { if (live) { setContent(value); setLoadError('') } }).catch(() => { if (live) { setContent(null); setLoadError('结果读取失败') } })
    return () => { live = false }
  }, [artifact.id, identityKey, retry])
  return <article className="result-card ledger-row enum-result-card">
    {artifact.status === 'stale' && <p className="mapping-warning">历史结果，可查看和下载。</p>}
    {loadError ? <p role="alert">{loadError} <button className="button-text" onClick={() => setRetry(retry + 1)}>重试</button></p> : content ? <EnumResultTable kind={artifact.kind as 'enum_values' | 'threat_mapping'} content={content} /> : <p role="status">正在读取结果…</p>}
    <div className="mapping-actions"><button className="button-secondary" onClick={onOpen}>查看产物</button><button className="button-secondary" onClick={onDownload} disabled={downloading}>下载结果</button></div>
    {error && <p className="mapping-error" role="alert">{error}</p>}
  </article>
}
