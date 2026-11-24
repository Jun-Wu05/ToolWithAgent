// 真浏览器冒烟（#459 回归位）：jsdom 无法覆盖「live FileList × React 延迟 updater」时序，
// 必须在真实 Chromium 中验证。需先 python v2/dev.py 启动栈，再运行：
//   npm run e2e                      （默认连 http://127.0.0.1:5173）
//   E2E_BASE_URL=... npm run e2e     （连其他实例）
// playwright 不可用或无浏览器时打印 SKIPPED 并以 0 退出——不进 CI 门禁。
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const base = process.env.E2E_BASE_URL || 'http://127.0.0.1:5173'

let chromium = null
for (const mod of ['playwright', 'playwright-core']) {
  try { ({ chromium } = await import(mod)); break } catch { /* 未安装则继续 */ }
}
if (!chromium) { console.log('[e2e] SKIPPED: 未安装 playwright（npm i -D playwright && npx playwright install chromium 后可用）'); process.exit(0) }

async function launchBrowser() {
  try { return await chromium.launch({ headless: true }) } catch { /* 回退本机浏览器 */ }
  const candidates = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  ]
  for (const executablePath of candidates) {
    try { return await chromium.launch({ headless: true, executablePath }) } catch { /* 试下一个 */ }
  }
  return null
}
const browser = await launchBrowser()
if (!browser) { console.log('[e2e] SKIPPED: 无可用 Chromium（npx playwright install chromium 后重试）'); process.exit(0) }

// 假 xlsx 只测「暂存清单即时渲染」（纯前端行为，选完不上传）；发送链用必然校验通过的 txt。
const dir = mkdtempSync(join(tmpdir(), 'v2-e2e-'))
const fakeXlsx = join(dir, '枚举映射.xlsx'); writeFileSync(fakeXlsx, 'not-a-real-workbook')
const txtLog = join(dir, 'parser-sample.txt'); writeFileSync(txtLog, '2026-11-24 10:00:00 login ok src=1.2.3.4')

const page = await browser.newPage()
const timeline = []
page.on('request', req => {
  if (req.method() !== 'POST') return
  if (req.url().includes('/files')) timeline.push('upload')
  if (/\/messages(\?|$)/.test(req.url())) timeline.push('message')
})
let failed = false
const fail = msg => { console.error('[e2e] FAIL:', msg); failed = true }

try {
  await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 15000 })
  await page.getByRole('button', { name: '＋ 新会话' }).click({ timeout: 10000 })
  await page.getByRole('button', { name: '＋ 添加文件' }).waitFor({ timeout: 10000 })

  // 1) #459 回归位：选择后暂存清单必须立即渲染（含假 xlsx 行）
  await page.setInputFiles('input[aria-label="选择文件"]', [fakeXlsx, txtLog])
  let stagingVisible = true
  await page.locator('div.upload-staging').waitFor({ timeout: 3000 }).catch(() => { stagingVisible = false })
  if (!stagingVisible) fail('暂存清单未即时渲染（#459 回归）')
  else console.log('[e2e] PASS: 暂存清单即时渲染（含 xlsx 默认用途行）')

  // 移除假 xlsx（其内容非法，上传会被校验拒绝而阻断发送链），仅携带 txt 走全链。
  await page.getByRole('button', { name: '移除 枚举映射.xlsx' }).click()

  // 2) 发送即携带（#457）：文本 + 剩余 1 份，一次发送 → 上传与校验完成后才发消息。
  await page.getByLabel('消息内容').fill('请解析这份日志')
  await page.getByRole('button', { name: '发送' }).click({ timeout: 5000 })
  const deadline = Date.now() + 40000
  while (Date.now() < deadline) {
    if (timeline.includes('upload') && timeline.includes('message')) break
    await page.waitForTimeout(500)
  }
  if (!timeline.includes('upload')) fail('上传请求未发出')
  else if (!timeline.includes('message')) fail('消息未在文件校验后发出（等待校验超时或链路断裂）')
  else if (timeline.indexOf('upload') > timeline.indexOf('message')) fail('消息先于上传发出（携带链路时序错误）')
  else console.log('[e2e] PASS: 发送即携带全链（upload → 等待校验 → message）')
} catch (error) {
  fail('脚本异常: ' + String(error).slice(0, 300))
}

rmSync(dir, { recursive: true, force: true })
await browser.close()
if (failed) process.exit(1)
console.log('[e2e] ALL PASS')
