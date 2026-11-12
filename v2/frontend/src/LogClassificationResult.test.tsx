import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LogClassificationCard, LogClassificationResult } from './LogClassificationResult'
import { ArtifactValues } from './BusinessWorkspace'
import { api, type ClassificationArtifact } from './api'

vi.mock('./api', () => ({
  api: { artifactContent: vi.fn() },
}))

const kvContent = {
  classification: {
    status: 'SUCCESS',
    log_format: 'KV',
    log_format_detail: 'KV',
    feature_field: 'name',
    feature_count: 3,
    classification_details: [
      { logtype: 'auth', meaning: '身份认证', count: 12, real_samples: 'time=2026-11-11T14:32:08+08:00|name=auth|src_ip=192.0.2.18|user=admin|action=login|result=success' },
      { logtype: 'traffic', meaning: '网络流量', count: 30, real_samples: ['time=2026-11-11T14:32:12+08:00|name=traffic|src_ip=192.0.2.24|dst_ip=198.51.100.10|dst_port=443|action=allow'] },
      { logtype: 'system', meaning: '系统运行', count: 1, sample: 'time=2026-11-11T14:33:20+08:00|name=system|device=fw-edge-01|event=config_saved' },
    ],
    analysis: { delimit: '|', tab: '=' },
    coverage: { total_lines: 45, matched_lines: 43, unmatched_lines: 2, unmatched_samples: ['time=2026-11-11T14:34:00+08:00|message=device heartbeat', 'time=2026-11-11T14:35:00+08:00|message=connection closed'] },
  },
  total_lines: 45,
  submission_eligible: true,
}

const jsonContent = {
  classification: {
    status: 'SUCCESS',
    log_format: 'JSON',
    feature_field: 'event.type',
    classification_details: [
      { logtype: 'auth', meaning: '身份认证', count: 2, real_samples: '{"timestamp":"2026-11-11T14:32:08+08:00","event":{"type":"auth","action":"login"},"src_ip":"192.0.2.18","result":"success"}' },
      { logtype: 'traffic', meaning: '网络流量', count: 1, real_samples: '{"timestamp":"2026-11-11T14:32:12+08:00","event":{"type":"traffic","action":"allow"},"dst_port":"443"}' },
    ],
    analysis: {},
    coverage: { total_lines: 3, matched_lines: 3, unmatched_lines: 0 },
  },
  total_lines: 3,
  submission_eligible: false,
}

const artifact: ClassificationArtifact = {
  id: 'cls-1', run_id: 'run-1', file_id: 'file-1', kind: 'log_classification', status: 'published',
  summary: { log_types: [], coverage: { matched_lines: 43, total_lines: 45 }, rule_summary: '格式 KV' },
  submission_eligible: false, created_at: '2026-11-12T02:00:00Z',
}

const fact = (label: string) => {
  const el = screen.getByText(label, { selector: '.lcr-fact-label' })
  return el.closest('.lcr-fact')?.textContent ?? ''
}
const clipboardStub = () => {
  const writeText = vi.fn(async () => {})
  const previous = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  return { writeText, restore: () => previous ? Object.defineProperty(navigator, 'clipboard', previous) : Reflect.deleteProperty(navigator, 'clipboard') }
}

beforeEach(() => { vi.mocked(api.artifactContent).mockReset() })
afterEach(() => { cleanup(); vi.resetAllMocks() })

describe('LogClassificationResult 数据展示', () => {
  it('KV 摘要展示格式、分类字段与两种分隔符', () => {
    render(<LogClassificationResult content={kvContent} />)
    expect(fact('日志格式')).toContain('KV')
    expect(fact('分类字段')).toContain('name')
    expect(fact('字段分隔符')).toContain('|')
    expect(fact('字段分隔符')).toContain('单竖线')
    expect(fact('键值分隔符')).toContain('=')
    expect(fact('键值分隔符')).toContain('等号')
    expect(screen.queryByText('字段路径')).toBeNull()
  })

  it('JSON 摘要展示字段路径与分类位置，隐藏分隔符', () => {
    render(<LogClassificationResult content={jsonContent} />)
    expect(fact('日志格式')).toContain('JSON')
    expect(fact('分类字段路径')).toContain('event.type')
    expect(fact('分类位置')).toContain('日志正文')
    expect(fact('分类方式')).toContain('未记录')
    expect(screen.queryByText('字段分隔符')).toBeNull()
    expect(screen.queryByText('键值分隔符')).toBeNull()
  })

  it.each([
    ['|', '单竖线'], ['||', '双竖线'], ['=', '等号'], [':', '冒号'],
    [' ', '空格'], ['\t', 'Tab（制表符）'], ['\\t', '字符序列（反斜杠 t）'],
    ['\\s', '空白匹配规则（正则）'], ['\\s+', '空白匹配规则（正则）'],
    ['pipe', '未识别'], ['判断失败', '未识别'], ['', '未识别'],
  ])('分隔符 %j 命名为 %s', (tab, name) => {
    render(<LogClassificationResult content={{ classification: { ...kvContent.classification, analysis: { delimit: '|', tab } } }} />)
    expect(fact('键值分隔符')).toContain(name)
  })

  it('日志头分类显示日志头特征，呈现全部类型', () => {
    render(<LogClassificationResult content={{ classification: { ...kvContent.classification, feature_field: '__header__' } }} />)
    expect(fact('分类字段')).toContain('日志头特征')
    expect(screen.getByText('共 3 类')).toBeTruthy()
  })

  it('每类一行展示类型、说明与样例预览', () => {
    render(<LogClassificationResult content={kvContent} />)
    expect(screen.getByRole('button', { name: 'auth' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'traffic' })).toBeTruthy()
    expect(screen.getByText('身份认证')).toBeTruthy()
    const authRow = screen.getByRole('button', { name: 'auth' }).closest('tr')!
    expect(authRow.textContent).toContain('name=auth')
    expect(authRow.textContent).toContain('src_ip=192.0.2.18')
  })

  it('缺失字段的占位：格式未识别、说明为破折号、无样例', () => {
    render(<LogClassificationResult content={{ classification: {
      classification_details: [{ logtype: 'x', sample: '' }, {}],
      analysis: {}, coverage: {},
    } }} />)
    expect(fact('日志格式')).toContain('未识别')
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getAllByText('暂无样例').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: '未命名类型' })).toBeTruthy()
  })

  it('标量类型值 0 与 false 按文本显示，不被真值判断吞掉', () => {
    render(<LogClassificationResult content={{ classification: {
      log_format: 'KV', classification_details: [
        { logtype: 0, meaning: '零值类型', sample: 'a=0|v=x' },
        { logtype: false, meaning: '假值类型', sample: 'a=false|v=y' },
      ],
      analysis: { delimit: '|', tab: '=' }, coverage: {},
    } }} />)
    expect(screen.getByRole('button', { name: '0' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'false' })).toBeTruthy()
  })

  it('real_samples 数组取首个非空字符串，否则回退 sample，复制不 trim 原文', async () => {
    const { writeText, restore } = clipboardStub()
    render(<LogClassificationResult content={{ classification: {
      log_format: 'KV', classification_details: [
        { logtype: 'a', real_samples: ['', 'second=kept'], sample: 'fallback' },
        { logtype: 'b', real_samples: '  leading space kept  ', sample: 'other' },
      ],
      analysis: {}, coverage: {},
    } }} />)
    expect(screen.getByText('second=kept')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'b' }))
    fireEvent.click(within(screen.getByRole('region', { name: '类型 b 详情' })).getByRole('button', { name: '复制' }))
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('  leading space kept  '))
    restore()
  })

  it('个别非对象明细行跳过并提示部分明细格式异常', () => {
    render(<LogClassificationResult content={{ classification: {
      log_format: 'KV', classification_details: [{ logtype: 'ok', sample: 'a=b' }, 'junk', 42],
      analysis: {}, coverage: {},
    } }} />)
    expect(screen.getByRole('button', { name: 'ok' })).toBeTruthy()
    expect(screen.getByText(/部分明细格式异常/)).toBeTruthy()
    expect(screen.getByText('共 1 类')).toBeTruthy()
  })

  it('classification 非对象与合法空明细分别提示', () => {
    const { unmount } = render(<LogClassificationResult content={{ classification: 'broken' }} />)
    expect(screen.getByText('分类明细格式不可用')).toBeTruthy()
    unmount()
    render(<LogClassificationResult content={{ classification: { classification_details: [] } }} />)
    expect(screen.getByText('当前产物没有分类明细')).toBeTruthy()
  })

  it('FAILED 与 UNSUPPORTED 显示真实原因，不绘制成功表', () => {
    const { unmount } = render(<LogClassificationResult content={{ classification: { status: 'FAILED', error: '特征定位失败' } }} />)
    expect(screen.getByText(/特征定位失败/)).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
    unmount()
    render(<LogClassificationResult content={{ classification: { status: 'UNSUPPORTED', error: '混合分隔符' } }} />)
    expect(screen.getByText(/混合分隔符/)).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('样例中的 HTML 与分隔符按文本渲染', () => {
    render(<LogClassificationResult content={{ classification: {
      log_format: 'KV', classification_details: [{ logtype: 'x', sample: '<script>alert(1)</script>|a=`b`|c="d"' }],
      analysis: { delimit: '|', tab: '=' }, coverage: {},
    } }} />)
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeTruthy()
  })
})

describe('LogClassificationResult 搜索分页展开', () => {
  const manyContent = () => {
    const details = Array.from({ length: 25 }, (_, i) => ({ logtype: `type-${String(i + 1).padStart(2, '0')}`, meaning: `第${i + 1}类`, sample: `seq=${i + 1}|note=row-${i + 1}` }))
    return { classification: { status: 'SUCCESS', log_format: 'KV', classification_details: details, analysis: { delimit: '|', tab: '=' }, coverage: {} } }
  }

  it('超过 20 类分页并可跨页翻阅全部类型', () => {
    render(<LogClassificationResult content={manyContent()} />)
    expect(screen.getByText('第 1–20 类，共 25 类')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'type-01' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'type-21' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(screen.getByText('第 21–25 类，共 25 类')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'type-25' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '上一页' }))
    expect(screen.getByRole('button', { name: 'type-01' })).toBeTruthy()
  })

  it('搜索先筛选后分页，命中跨页类型并回第一页', () => {
    render(<LogClassificationResult content={manyContent()} />)
    fireEvent.change(screen.getByRole('textbox', { name: '搜索类型、说明或样例' }), { target: { value: 'ROW-25' } })
    expect(screen.getByRole('button', { name: 'type-25' })).toBeTruthy()
    expect(screen.getByText('找到 1 类 / 共 25 类')).toBeTruthy()
    fireEvent.change(screen.getByRole('textbox', { name: '搜索类型、说明或样例' }), { target: { value: '不存在的内容' } })
    expect(screen.getByText('没有匹配的类型或样例，请更换搜索词。')).toBeTruthy()
  })

  it('行展开独立并存，重名类型各自展开', () => {
    render(<LogClassificationResult content={{ classification: {
      log_format: 'KV', classification_details: [
        { logtype: 'dup', meaning: '第一种', sample: 'first=1' },
        { logtype: 'dup', meaning: '第二种', sample: 'second=2' },
      ],
      analysis: {}, coverage: {},
    } }} />)
    const [first, second] = screen.getAllByRole('button', { name: 'dup' })
    fireEvent.click(first)
    fireEvent.click(second)
    const regions = screen.getAllByRole('region', { name: '类型 dup 详情' })
    expect(regions.length).toBe(2)
    expect(regions[0].textContent).toContain('first=1')
    expect(regions[1].textContent).toContain('second=2')
  })

  it('搜索与分页切换保留展开状态', () => {
    render(<LogClassificationResult content={manyContent()} />)
    fireEvent.click(screen.getByRole('button', { name: 'type-01' }))
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    fireEvent.click(screen.getByRole('button', { name: '上一页' }))
    expect(screen.getAllByText('seq=1|note=row-1').length).toBeGreaterThan(0)
  })

  it('批量展开按钮按页生效：20 类内为全部，分页时为本页', () => {
    const { unmount } = render(<LogClassificationResult content={kvContent} />)
    fireEvent.click(screen.getByRole('button', { name: '展开全部样例' }))
    expect(screen.getAllByText('完整样例').length).toBe(3)
    fireEvent.click(screen.getByRole('button', { name: '收起全部样例' }))
    expect(screen.queryByText('完整样例')).toBeNull()
    unmount()
    render(<LogClassificationResult content={manyContent()} />)
    fireEvent.click(screen.getByRole('button', { name: '展开本页样例' }))
    expect(screen.getAllByText('完整样例').length).toBe(20)
    fireEvent.click(screen.getByRole('button', { name: '下一页' }))
    expect(screen.queryByText('完整样例')).toBeNull()
  })

  it('展开内容依次为完整样例、分类依据、格式规则，解析规则只读展示', () => {
    render(<LogClassificationResult content={kvContent} />)
    fireEvent.click(screen.getByRole('button', { name: 'auth' }))
    const detail = screen.getByRole('region', { name: '类型 auth 详情' })
    expect(within(detail).getByText('完整样例')).toBeTruthy()
    expect(detail.textContent).toContain('name = auth')
    expect(detail.textContent).toContain('字段分隔')
    expect(detail.textContent).toContain('键值分隔')
    fireEvent.click(within(detail).getByText('查看解析规则详情'))
    expect(within(detail).getByText(/按字段分隔符/)).toBeTruthy()
  })

  it('无 analysis 数据时提示未记录解析规则详情', () => {
    render(<LogClassificationResult content={{ classification: { log_format: 'KV', classification_details: [{ logtype: 'x', sample: 'a=b' }], analysis: {}, coverage: {} } }} />)
    fireEvent.click(screen.getByRole('button', { name: 'x' }))
    fireEvent.click(screen.getByText('查看解析规则详情'))
    expect(screen.getByText('未记录解析规则详情')).toBeTruthy()
  })

  it('取消换行切换后可恢复自动换行', () => {
    render(<LogClassificationResult content={kvContent} />)
    fireEvent.click(screen.getByRole('button', { name: 'auth' }))
    const detail = screen.getByRole('region', { name: '类型 auth 详情' })
    fireEvent.click(within(detail).getByRole('button', { name: '取消换行' }))
    const pre = detail.querySelector('pre')
    expect(pre?.className).toContain('lcr-nowrap')
    fireEvent.click(within(detail).getByRole('button', { name: '自动换行' }))
    expect(pre?.className).not.toContain('lcr-nowrap')
  })

  it('可定位字段时样例高亮，多处命中不高亮', () => {
    render(<LogClassificationResult content={kvContent} />)
    expect(screen.getByRole('button', { name: 'auth' }).closest('tr')?.querySelector('mark')?.textContent).toContain('name=auth')
    cleanup()
    render(<LogClassificationResult content={{ classification: {
      log_format: 'KV', feature_field: 'name', classification_details: [{ logtype: 'duo', sample: 'name=duo|echo=name=duo' }],
      analysis: { delimit: '|', tab: '=' }, coverage: {},
    } }} />)
    expect(screen.getByRole('button', { name: 'duo' }).closest('tr')?.querySelector('mark')).toBeNull()
  })

  it('未匹配行独立提示与查看，未匹配不混入类型数', () => {
    render(<LogClassificationResult content={kvContent} />)
    expect(screen.getByText('有 2 行未匹配分类字段，未计入以上类型。')).toBeTruthy()
    expect(screen.getByText('共 3 类')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '查看未匹配样例' }))
    expect(screen.getByText(/device heartbeat/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '收起未匹配样例' }))
  })

  it('未匹配无样例时说明未提供，未匹配为 0 时不提示', () => {
    const { unmount } = render(<LogClassificationResult content={{ classification: { ...kvContent.classification, coverage: { total_lines: 45, matched_lines: 45, unmatched_lines: 0 } } }} />)
    expect(screen.queryByText(/未匹配分类字段/)).toBeNull()
    unmount()
    render(<LogClassificationResult content={{ classification: { ...kvContent.classification, coverage: { total_lines: 45, matched_lines: 43, unmatched_lines: 2, unmatched_samples: [] } } }} />)
    fireEvent.click(screen.getByRole('button', { name: '查看未匹配样例' }))
    expect(screen.getByText('未提供未匹配样例')).toBeTruthy()
  })
})

describe('LogClassificationResult JSON 样例格式化', () => {
  it('格式化仅改显示，复制保留原始样例', async () => {
    const { writeText, restore } = clipboardStub()
    render(<LogClassificationResult content={jsonContent} />)
    fireEvent.click(screen.getByRole('button', { name: 'auth' }))
    const detail = screen.getByRole('region', { name: '类型 auth 详情' })
    fireEvent.click(within(detail).getByRole('button', { name: '格式化 JSON' }))
    expect(within(detail).getByText('样例日志 · 格式化视图')).toBeTruthy()
    fireEvent.click(within(detail).getByRole('button', { name: '复制' }))
    await vi.waitFor(() => expect(writeText).toHaveBeenCalledWith('{"timestamp":"2026-11-11T14:32:08+08:00","event":{"type":"auth","action":"login"},"src_ip":"192.0.2.18","result":"success"}'))
    fireEvent.click(within(detail).getByRole('button', { name: '查看原始日志' }))
    expect(within(detail).getByText('完整样例')).toBeTruthy()
    restore()
  })

  it('非法 JSON 保留原文并提示', () => {
    render(<LogClassificationResult content={{ classification: {
      log_format: 'JSON', feature_field: 'event.type', classification_details: [{ logtype: 'broken', real_samples: '{"timestamp": truncated' }],
      analysis: {}, coverage: {},
    } }} />)
    fireEvent.click(screen.getByRole('button', { name: 'broken' }))
    const detail = screen.getByRole('region', { name: '类型 broken 详情' })
    fireEvent.click(within(detail).getByRole('button', { name: '格式化 JSON' }))
    expect(screen.getByText('样例无法格式化，已保留原文')).toBeTruthy()
    expect(detail.textContent).toContain('{"timestamp": truncated')
  })
})

describe('LogClassificationCard 读取与隔离', () => {
  it('加载中提示读取分类明细，成功后展示结果与操作', async () => {
    let release!: (value: Record<string, unknown>) => void
    vi.mocked(api.artifactContent).mockImplementation(() => new Promise(resolve => { release = resolve }))
    const { rerender } = render(<LogClassificationCard artifact={artifact} identityKey="u1:conv-1:cls-1" actions={<button>业务操作</button>} />)
    expect(screen.getByText('正在读取分类明细…')).toBeTruthy()
    release(kvContent)
    await screen.findByRole('button', { name: 'auth' })
    expect(screen.getByRole('button', { name: '业务操作' })).toBeTruthy()
    expect(vi.mocked(api.artifactContent)).toHaveBeenCalledWith('cls-1')
    rerender(<LogClassificationCard artifact={artifact} identityKey="u1:conv-1:cls-1" actions={<button>业务操作</button>} />)
    expect(vi.mocked(api.artifactContent)).toHaveBeenCalledTimes(1)
  })

  it('请求失败局部重试，重试成功恢复', async () => {
    vi.mocked(api.artifactContent).mockRejectedValueOnce(new Error('无权访问'))
    render(<LogClassificationCard artifact={artifact} identityKey="u1:conv-1:cls-1" />)
    expect(await screen.findByText(/无权访问/)).toBeTruthy()
    vi.mocked(api.artifactContent).mockResolvedValueOnce(kvContent)
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByRole('button', { name: 'auth' })).toBeTruthy()
  })

  it('切换产物的迟到响应不回填新视图', async () => {
    let releaseFirst!: (value: Record<string, unknown>) => void
    vi.mocked(api.artifactContent).mockImplementationOnce(() => new Promise(resolve => { releaseFirst = resolve }))
    vi.mocked(api.artifactContent).mockResolvedValueOnce(jsonContent)
    const second = { ...artifact, id: 'cls-2' }
    const { rerender } = render(<LogClassificationCard artifact={artifact} identityKey="u1:conv-1:cls-1" />)
    rerender(<LogClassificationCard artifact={second} identityKey="u1:conv-1:cls-2" />)
    expect(await screen.findByRole('button', { name: 'traffic' })).toBeTruthy()
    releaseFirst(kvContent)
    await vi.waitFor(() => expect(screen.getByText('共 2 类')).toBeTruthy())
    expect(screen.queryByRole('button', { name: 'system' })).toBeNull()
  })

  it('切换身份重新读取，旧身份迟到响应不写入', async () => {
    let releaseFirst!: (value: Record<string, unknown>) => void
    vi.mocked(api.artifactContent).mockImplementationOnce(() => new Promise(resolve => { releaseFirst = resolve }))
    vi.mocked(api.artifactContent).mockResolvedValueOnce(jsonContent)
    const { rerender } = render(<LogClassificationCard artifact={artifact} identityKey="u1:conv-1:cls-1" />)
    rerender(<LogClassificationCard artifact={artifact} identityKey="u2:conv-2:cls-1" />)
    expect(await screen.findByRole('button', { name: 'traffic' })).toBeTruthy()
    releaseFirst(kvContent)
    await vi.waitFor(() => expect(screen.getByText('共 2 类')).toBeTruthy())
  })

  it('历史产物提示历史结果', async () => {
    vi.mocked(api.artifactContent).mockResolvedValue(kvContent)
    render(<LogClassificationCard artifact={{ ...artifact, status: 'stale' }} identityKey="u1:conv-1:cls-1" />)
    expect(await screen.findByText('历史结果，可查看和下载。')).toBeTruthy()
  })
})

describe('ArtifactValues 分类分支', () => {
  it('log_classification 复用结果组件且不再请求内容', () => {
    render(<ArtifactValues artifact={artifact} content={kvContent} />)
    expect(screen.getByRole('button', { name: 'auth' })).toBeTruthy()
    expect(api.artifactContent).not.toHaveBeenCalled()
  })
})
