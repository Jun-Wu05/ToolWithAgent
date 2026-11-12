import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, type ClassificationArtifact } from './api'
import { CopyButton } from './VisualPrimitives'
import './log-classification.css'

// 批准设计 log-type-results-v1：分类摘要 + 三列表格 + 展开详情。
// 纯展示组件，不发业务写请求；内容读取只在 LogClassificationCard 内发生。

const HEADER_FIELD = '__header__'
const PAGE_SIZE = 20
const separatorNames: Record<string, string> = {
  '|': '单竖线', '||': '双竖线', '=': '等号', ':': '冒号', ' ': '空格', '\t': 'Tab（制表符）',
  '\\t': '字符序列（反斜杠 t）', '\\s': '空白匹配规则（正则）', '\\s+': '空白匹配规则（正则）',
}
const separatorName = (raw: unknown): string | null => (typeof raw === 'string' && raw !== '' && raw !== '判断失败' ? (separatorNames[raw] ?? '未识别') : null)
const asText = (value: unknown): string | null => {
  if (typeof value === 'string') return value === '' ? null : value
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : null
  if (typeof value === 'boolean' || typeof value === 'bigint') return String(value)
  return null
}
const countOf = (value: unknown): number | null => (typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null)

type Sep = { raw: string; name: string }
type Row = { index: number; type: string; meaning: string; sample: string | null; needle: string | null }
type Normalized =
  | { kind: 'error'; message: string }
  | { kind: 'empty' }
  | { kind: 'ok'; isJson: boolean; logFormat: string; formatDetail: string; featureField: string; headerFeature: boolean; delimit: Sep | null; tab: Sep | null; rows: Row[]; invalidCount: number; matched: number | null; total: number | null; unmatched: number | null; unmatchedSamples: string[]; analysisEntries: [string, string][] }

function normalize(content: Record<string, unknown>): Normalized {
  const classification = content.classification
  if (typeof classification !== 'object' || classification === null || Array.isArray(classification)) return { kind: 'error', message: '分类明细格式不可用' }
  const source = classification as Record<string, unknown>
  const status = typeof source.status === 'string' ? source.status : ''
  if (status === 'FAILED') return { kind: 'error', message: '日志解析失败：' + (typeof source.error === 'string' && source.error ? source.error : '未知错误') }
  if (status === 'UNSUPPORTED') return { kind: 'error', message: '该数据不符合支持的 KV/JSON 日志格式：' + (typeof source.error === 'string' && source.error ? source.error : '格式不支持') }
  const rawFormat = asText(source.log_format)
  const formatUpper = rawFormat?.toUpperCase() ?? ''
  const isJson = formatUpper === 'JSON'
  const isKv = formatUpper === 'KV'
  const featureField = asText(source.feature_field) ?? ''
  const headerFeature = featureField === HEADER_FIELD
  const analysis = typeof source.analysis === 'object' && source.analysis !== null && !Array.isArray(source.analysis) ? source.analysis as Record<string, unknown> : null
  const delimitName = separatorName(analysis?.delimit)
  const tabName = separatorName(analysis?.tab)
  const delimit: Sep | null = delimitName ? { raw: String(analysis?.delimit), name: delimitName } : null
  const tab: Sep | null = tabName ? { raw: String(analysis?.tab), name: tabName } : null
  const details = source.classification_details
  const rows: Row[] = []
  let invalidCount = 0
  if (Array.isArray(details)) {
    details.forEach((detail, index) => {
      if (typeof detail !== 'object' || detail === null || Array.isArray(detail)) { invalidCount++; return }
      const record = detail as Record<string, unknown>
      const type = asText(record.logtype) ?? asText(record.name) ?? '未命名类型'
      const meaning = asText(record.meaning) ?? '—'
      let sample: string | null = null
      const real = record.real_samples
      if (typeof real === 'string' && real !== '') sample = real
      else if (Array.isArray(real)) { const first = real.find(item => typeof item === 'string' && item !== ''); if (first !== undefined) sample = first }
      if (sample === null) { const fallback = asText(record.sample); if (fallback !== null) sample = fallback }
      rows.push({ index, type, meaning, sample, needle: locateNeedle({ isJson, featureField, headerFeature, tab: tab?.raw ?? null, type, sample }) })
    })
  }
  const coverage = typeof source.coverage === 'object' && source.coverage !== null && !Array.isArray(source.coverage) ? source.coverage as Record<string, unknown> : {}
  const unmatchedSamples = Array.isArray(coverage.unmatched_samples) ? coverage.unmatched_samples.filter((item): item is string => typeof item === 'string' && item !== '') : []
  const analysisEntries: [string, string][] = []
  if (analysis) for (const [key, value] of Object.entries(analysis)) if (key !== 'delimit' && key !== 'tab' && value !== null && value !== undefined && value !== '') analysisEntries.push([key, typeof value === 'object' ? JSON.stringify(value) : String(value)])
  const rawDetail = asText(source.log_format_detail)
  return {
    kind: rows.length ? 'ok' : 'empty', isJson, logFormat: rawFormat ?? '未识别',
    formatDetail: rawDetail !== null && rawDetail !== rawFormat ? rawDetail : (isKv ? '键值对' : ''),
    featureField, headerFeature, delimit, tab, rows, invalidCount,
    matched: countOf(coverage.matched_lines), total: countOf(coverage.total_lines),
    unmatched: countOf(coverage.unmatched_lines), unmatchedSamples,
    analysisEntries,
  }
}

// 高亮仅在字段值可唯一定位时添加：命中 0 次或多次都不加。
function locateNeedle({ isJson, featureField, headerFeature, tab, type, sample }: { isJson: boolean; featureField: string; headerFeature: boolean; tab: string | null; type: string; sample: string | null }): string | null {
  if (!sample || headerFeature || type === '未命名类型') return null
  const candidates: string[] = []
  if (isJson) {
    const leaf = featureField.split('.').at(-1)
    if (!leaf) return null
    candidates.push(`"${leaf}":"${type}"`, `"${leaf}": "${type}"`)
  } else {
    if (!featureField || !tab) return null
    candidates.push(`${featureField}${tab}${type}`)
  }
  for (const needle of candidates) if (sample.split(needle).length === 2) return needle
  return null
}

function withHighlight(text: string, needle: string | null, keyBase: string): ReactNode {
  if (!needle || !text.includes(needle)) return text
  const [before, ...rest] = text.split(needle)
  return <>{before}<mark key={keyBase + 'mark'}>{needle}</mark>{rest.join(needle)}</>
}

const readableTime = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''
const separatorText = (sep: Sep | null) => sep ? <><code className="lcr-token">{sep.raw}</code><small>{sep.name}</small></> : <small>未识别</small>

export function LogClassificationResult({ content, rowKeyPrefix = '' }: { content: Record<string, unknown>; rowKeyPrefix?: string }) {
  const data = useMemo(() => normalize(content), [content])
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set())
  const [nowrap, setNowrap] = useState<Set<number>>(() => new Set())
  const [formatted, setFormatted] = useState<Set<number>>(() => new Set())
  const [formatError, setFormatError] = useState<Set<number>>(() => new Set())
  const [unmatchedOpen, setUnmatchedOpen] = useState(false)
  if (data.kind === 'error') return <p className="mapping-error" role="alert">{data.message}</p>
  if (data.kind === 'empty') return <p>当前产物没有分类明细</p>
  const { rows, isJson, featureField, headerFeature } = data
  const keyword = query.trim().toLowerCase()
  const filtered = keyword ? rows.filter(row => `${row.type} ${row.meaning} ${row.sample ?? ''}`.toLowerCase().includes(keyword)) : rows
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount)
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)
  const hasPagination = filtered.length > PAGE_SIZE
  const filteredExpanded = filtered.filter(row => expanded.has(row.index)).length
  const pageExpanded = pageRows.some(row => expanded.has(row.index))
  const detailId = (index: number) => `lcr-detail-${rowKeyPrefix}-${index}`
  const toggle = (index: number) => setExpanded(current => {
    const next = new Set(current)
    if (next.has(index)) next.delete(index); else next.add(index)
    return next
  })
  const toggleSet = (key: number, set: (updater: (current: Set<number>) => Set<number>) => void) => set(current => {
    const next = new Set(current)
    if (next.has(key)) next.delete(key); else next.add(key)
    return next
  })
  const toggleBatch = () => {
    const targets = pageRows.map(row => row.index)
    const collapse = hasPagination ? pageExpanded : filteredExpanded > 0
    setExpanded(current => {
      const next = new Set(current)
      for (const index of targets) {
        if (collapse) next.delete(index)
        else next.add(index)
      }
      return next
    })
  }
  const formattedSample = (row: Row): string => {
    if (!formatted.has(row.index) || row.sample === null) return row.sample ?? ''
    try { return JSON.stringify(JSON.parse(row.sample), null, 2) } catch { return row.sample }
  }
  const toggleFormat = (row: Row) => {
    if (row.sample === null) return
    try {
      JSON.parse(row.sample)
      toggleSet(row.index, setFormatted)
      setFormatError(current => { const next = new Set(current); next.delete(row.index); return next })
    } catch {
      setFormatError(current => { const next = new Set(current); next.add(row.index); return next })
    }
  }
  const coverageText = data.matched !== null && data.total !== null ? `（覆盖 ${data.matched}/${data.total} 行）` : ''
  const facts: [string, ReactNode][] = isJson ? [
    ['日志格式', <span key="format">{data.logFormat}{data.formatDetail && <small>{data.formatDetail}</small>}</span>],
    ['分类字段路径', featureField ? <code key="field">{featureField}</code> : <span key="field">未记录</span>],
    ['分类位置', headerFeature ? <span key="pos">日志头特征</span> : featureField ? <span key="pos">日志正文</span> : <span key="pos">未记录</span>],
    ['分类方式', <span key="mode">未记录</span>],
  ] : [
    ['日志格式', <span key="format">{data.logFormat}{data.formatDetail && <small>{data.formatDetail}</small>}</span>],
    ['分类字段', headerFeature ? <span key="field">日志头特征</span> : featureField ? <><code key="field">{featureField}</code><small>日志正文</small></> : <span key="field">未记录</span>],
    ['字段分隔符', separatorText(data.delimit)],
    ['键值分隔符', separatorText(data.tab)],
  ]
  const fieldLabel = headerFeature ? '日志头特征' : featureField ? `${featureField} 字段` : ''
  const hasRuleInfo = !!(data.delimit || data.tab || data.analysisEntries.length || (isJson && featureField))
  const ruleSentence = !hasRuleInfo ? null : isJson
    ? (featureField ? `先按 JSON 结构读取日志正文，再通过 ${featureField} 定位分类值。` : '先按 JSON 结构读取日志正文，再定位分类值。')
    : data.delimit && data.tab
      ? `按字段分隔符 ${data.delimit.raw} 读取键值对，再按 ${data.tab.raw} 区分键和值${featureField ? `，以 ${featureField} 的值分类` : ''}。单竖线 | 与双竖线 || 必须保持区别。`
      : featureField ? `以 ${featureField} 的值分类。` : '分类规则未记录。'
  return <section className="lcr" aria-label="日志类型提取结果">
    <p className="lcr-intro">{fieldLabel ? `已按 ${fieldLabel}识别出 ${rows.length} 类日志。` : `已识别出 ${rows.length} 类日志。`}每类保留一条样例，展开即可查看完整内容。</p>
    {data.invalidCount > 0 && <p className="lcr-invalid" role="status">部分明细格式异常，已跳过 {data.invalidCount} 项无效行。</p>}
    <div className={'lcr-summary' + (isJson ? ' lcr-summary-json' : '')}>{facts.map(([label, value]) => <div className="lcr-fact" key={label}><span className="lcr-fact-label">{label}</span><div className="lcr-fact-value">{value}</div></div>)}</div>
    <div className="lcr-toolbar">
      <div className="lcr-table-title"><h4>分类结果</h4><span className="lcr-count">共 {rows.length} 类</span>{coverageText && <span className="lcr-coverage-count">{coverageText}</span>}</div>
      <label className="lcr-search"><input aria-label="搜索类型、说明或样例" placeholder="搜索类型、说明或样例" value={query} onChange={event => { setQuery(event.target.value); setPage(1) }} /></label>
    </div>
    <div className="lcr-table-wrap"><table className="lcr-table">
      <thead><tr><th scope="col">日志类型</th><th scope="col">类型说明</th><th scope="col">样例日志</th></tr></thead>
      <tbody>
        {pageRows.length ? pageRows.map(row => {
          const open = expanded.has(row.index)
          return open ? <SampleRow key={row.index} row={row} detailId={detailId(row.index)} onToggle={() => toggle(row.index)} needle={row.needle} meaning={row.meaning} nowrap={nowrap.has(row.index)} onToggleWrap={() => toggleSet(row.index, setNowrap)} isJson={isJson} formatted={formatted.has(row.index)} formatFailed={formatError.has(row.index)} displaySample={formattedSample(row)} onToggleFormat={() => toggleFormat(row)} featureField={featureField} headerFeature={headerFeature} delimit={data.delimit} tab={data.tab} ruleSentence={ruleSentence} analysisEntries={data.analysisEntries} />
            : <tr className="lcr-data-row" key={row.index}><td><button type="button" className="lcr-toggle" aria-expanded={false} aria-controls={detailId(row.index)} onClick={() => toggle(row.index)}><span className="lcr-chevron" aria-hidden="true">▸</span><code>{row.type}</code></button></td><td className="lcr-meaning">{row.meaning}</td><td>{row.sample === null ? <span className="lcr-nosample">暂无样例</span> : <code className="lcr-preview">{withHighlight(row.sample, row.needle, 'p' + row.index)}</code>}</td></tr>
        }) : <tr><td colSpan={3} className="lcr-empty">没有匹配的类型或样例，请更换搜索词。</td></tr>}
      </tbody>
    </table></div>
    <div className="lcr-footer">
      <span className="lcr-footer-count">{keyword ? `找到 ${filtered.length} 类 / 共 ${rows.length} 类` : hasPagination ? '' : `已展示全部 ${rows.length} 类`}</span>
      <span className="lcr-footer-actions">
        {hasPagination && <>
          <span className="lcr-page-info">第 {Math.min((safePage - 1) * PAGE_SIZE + 1, filtered.length)}–{Math.min(safePage * PAGE_SIZE, filtered.length)} 类，共 {filtered.length} 类</span>
          <button type="button" className="button-text" onClick={() => setPage(safePage - 1)} disabled={safePage <= 1}>上一页</button>
          <button type="button" className="button-text" onClick={() => setPage(safePage + 1)} disabled={safePage >= pageCount}>下一页</button>
        </>}
        <button type="button" className="button-text" onClick={toggleBatch}>{hasPagination ? (pageExpanded ? '收起本页样例' : '展开本页样例') : (filteredExpanded > 0 ? '收起全部样例' : '展开全部样例')}</button>
      </span>
    </div>
    {data.unmatched !== null && data.unmatched > 0 && <div className="lcr-unmatched-bar" role="note">
      <span className="lcr-unmatched-icon" aria-hidden="true">⚠</span>
      <span>有 {data.unmatched} 行未匹配分类字段，未计入以上类型。</span>
      <button type="button" className="button-text" aria-expanded={unmatchedOpen} onClick={() => setUnmatchedOpen(!unmatchedOpen)}>{unmatchedOpen ? '收起未匹配样例' : '查看未匹配样例'}</button>
    </div>}
    {unmatchedOpen && (data.unmatched !== null && data.unmatched > 0) && <pre className="lcr-sample-full lcr-unmatched">{data.unmatchedSamples.length ? data.unmatchedSamples.join('\n\n') : '未提供未匹配样例'}</pre>}
  </section>
}

function SampleRow({ row, detailId, onToggle, needle, meaning, nowrap, onToggleWrap, isJson, formatted, formatFailed, displaySample, onToggleFormat, featureField, headerFeature, delimit, tab, ruleSentence, analysisEntries }: {
  row: Row; detailId: string; onToggle: () => void; needle: string | null; meaning: string
  nowrap: boolean; onToggleWrap: () => void; isJson: boolean; formatted: boolean; formatFailed: boolean; displaySample: string; onToggleFormat: () => void
  featureField: string; headerFeature: boolean; delimit: Sep | null; tab: Sep | null; ruleSentence: string | null; analysisEntries: [string, string][]
}) {
  return <>
    <tr className="lcr-data-row is-open"><td><button type="button" className="lcr-toggle" aria-expanded={true} aria-controls={detailId} onClick={onToggle}><span className="lcr-chevron" aria-hidden="true">▾</span><code>{row.type}</code></button></td><td className="lcr-meaning">{row.meaning}</td><td>{row.sample === null ? <span className="lcr-nosample">暂无样例</span> : <code className="lcr-preview">{withHighlight(row.sample, needle, 'p' + row.index)}</code>}</td></tr>
    <tr className="lcr-detail-row"><td colSpan={3}><div className="lcr-detail" id={detailId} role="region" aria-label={`类型 ${row.type} 详情`}>
      <div className="lcr-detail-head">
        <span>{formatted ? '样例日志 · 格式化视图' : '完整样例'}</span>
        {row.sample !== null && <span className="lcr-detail-tools">
          {isJson && <button type="button" className="button-text" onClick={onToggleFormat}>{formatted ? '查看原始日志' : '格式化 JSON'}</button>}
          <button type="button" className="button-text" onClick={onToggleWrap}>{nowrap ? '自动换行' : '取消换行'}</button>
          <CopyButton text={row.sample} label="复制" />
        </span>}
      </div>
      {formatFailed && <p className="lcr-format-error" role="status">样例无法格式化，已保留原文</p>}
      {row.sample !== null && <pre className={'lcr-sample-full' + (nowrap ? ' lcr-nowrap' : '')}>{formatted ? displaySample : withHighlight(row.sample, needle, 'f' + row.index)}</pre>}
      <div className="lcr-detail-meta">
        <span>类型说明{'\u3000'}<strong>{meaning}</strong></span>
        <span>分类依据{'\u3000'}{headerFeature ? <strong>日志头特征 · {row.type}</strong> : <><code>{featureField || '未记录'}</code> = <code>{row.type}</code></>}</span>
        {isJson
          ? <span>分类位置{'\u3000'}<strong>{headerFeature ? '日志头特征' : featureField.includes('.') ? '日志正文 · 嵌套字段' : '日志正文'}</strong></span>
          : <><span>字段分隔{'\u3000'}{delimit ? <><code>{delimit.raw}</code> {delimit.name}</> : '未识别'}</span><span>键值分隔{'\u3000'}{tab ? <><code>{tab.raw}</code> {tab.name}</> : '未识别'}</span></>}
      </div>
      <details className="lcr-rule-info"><summary>查看解析规则详情</summary>{(ruleSentence || analysisEntries.length) ? <>{ruleSentence && <p>{ruleSentence}</p>}{analysisEntries.map(([key, value]) => <p key={key}><code>{key}</code>：{value}</p>)}</> : <p>未记录解析规则详情</p>}</details>
    </div></td></tr>
  </>
}

export function LogClassificationCard({ artifact, identityKey, actions }: { artifact: ClassificationArtifact; identityKey: string; actions?: ReactNode }) {
  const [state, setState] = useState<{ status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; content: Record<string, unknown> }>({ status: 'loading' })
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let live = true
    setState({ status: 'loading' })
    api.artifactContent(artifact.id)
      .then(content => { if (live) setState({ status: 'ready', content }) })
      .catch(caught => { if (live) setState({ status: 'error', message: caught instanceof Error ? caught.message : '分类明细读取失败。' }) })
    return () => { live = false }
  }, [artifact.id, identityKey, retry])
  return <article className="result-card ledger-row lcr-card">
    <div className="result-heading"><strong>日志类型提取完成</strong><span>{readableTime(artifact.created_at)}</span></div>
    {artifact.status === 'stale' && <p className="mapping-warning">历史结果，可查看和下载。</p>}
    {state.status === 'loading' && <p role="status">正在读取分类明细…</p>}
    {state.status === 'error' && <p role="alert" className="mapping-error">{state.message} <button type="button" className="button-text" onClick={() => setRetry(retry + 1)}>重试</button></p>}
    {state.status === 'ready' && <LogClassificationResult content={state.content} rowKeyPrefix={artifact.id} />}
    {actions && <div className="lcr-actions">{actions}</div>}
  </article>
}
