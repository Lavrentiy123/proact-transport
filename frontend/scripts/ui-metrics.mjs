// UI metrics of the audit (AUDIT.md, PLAN.MD 1.5.3): text contrast, text under 11 px, targets under 24 px
// and horizontal overflow, for the demo and the live stream at 375, 768 and 1440 px.
//
//   node scripts/ui-metrics.mjs [--base http://127.0.0.1:5173/] [--out ui-metrics/report.json] [--strict]
//
// Without --base the script starts Vite on 5173 and the stub (STUB_CASE=status-skew) on 8000 itself.
// --strict exits with code 1 when any violation is found. PW_CHROMIUM_PATH selects a local Chromium.
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const args = process.argv.slice(2)
const option = (name, fallback) => {
  const index = args.indexOf(name)
  return index >= 0 && args[index + 1] && !args[index + 1].startsWith('--') ? args[index + 1] : fallback
}
const strict = args.includes('--strict')
const out = resolve(option('--out', 'ui-metrics/report.json'))
const external = option('--base', process.env.BASE)
const WIDTHS = [375, 768, 1440]
const MIN_FONT_PX = 11
const MIN_TARGET_PX = 24
const root = fileURLToPath(new URL('..', import.meta.url))

const auditFn = ({ minFont, minTarget }) => {
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/)
    if (!m) return null
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number)
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
  }
  const lum = ({ r, g, b }) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
  }
  const blend = (top, bottom) => ({ r: top.r * top.a + bottom.r * (1 - top.a), g: top.g * top.a + bottom.g * (1 - top.a), b: top.b * top.a + bottom.b * (1 - top.a), a: 1 })
  const pageBackground = parse(getComputedStyle(document.body).backgroundColor) ?? { r: 255, g: 255, b: 255, a: 1 }
  const bgOf = (el) => {
    const stack = []
    for (let n = el; n; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor)
      if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break }
    }
    let base = pageBackground.a >= 1 ? pageBackground : { r: 255, g: 255, b: 255, a: 1 }
    for (let i = stack.length - 1; i >= 0; i--) base = blend(stack[i], base)
    return base
  }
  const visible = (el) => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el)
    // 1×1 px boxes are visually hidden text for screen readers.
    return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0
  }
  const describe = (el) => (el.getAttribute('aria-label') || [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(' ') || el.textContent || '').trim().slice(0, 60)
  const textEls = [...document.querySelectorAll('body *')].filter((el) => visible(el) && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()) && !el.closest('.maplibregl-canvas-container'))
  const text = textEls.map((el) => {
    const s = getComputedStyle(el)
    const fg = parse(s.color); const bg = bgOf(el)
    const L1 = lum(blend(fg, bg)), L2 = lum(bg)
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05)
    const size = parseFloat(s.fontSize)
    const weight = Number(s.fontWeight) || 400
    const large = size >= 24 || (size >= 18.66 && weight >= 700)
    return { text: describe(el), tag: el.tagName.toLowerCase(), size, weight, ratio: Math.round(ratio * 100) / 100, required: large ? 3 : 4.5 }
  })
  const targets = [...document.querySelectorAll('button, select, input, a[href], summary, [role="button"]')].filter(visible).map((el) => {
    const r = el.getBoundingClientRect()
    return { tag: el.tagName.toLowerCase(), label: describe(el), w: Math.round(r.width), h: Math.round(r.height) }
  })
  const fontSizes = {}
  for (const item of text) fontSizes[`${item.size}px`] = (fontSizes[`${item.size}px`] ?? 0) + 1
  return {
    viewport: { w: innerWidth, h: innerHeight },
    overflow: { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, docHeight: document.documentElement.scrollHeight },
    lowContrast: text.filter((item) => item.ratio < item.required).sort((a, b) => a.ratio - b.ratio),
    smallText: text.filter((item) => item.size < minFont).sort((a, b) => a.size - b.size),
    smallTargets: targets.filter((item) => item.w < minTarget || item.h < minTarget),
    minContrast: text.reduce((m, item) => Math.min(m, item.ratio), 99),
    textCount: text.length,
    targetsTotal: targets.length,
    fontSizes,
  }
}

async function healthy(url) {
  try { return (await fetch(url)).ok } catch { return false }
}

async function waitFor(url, ms = 20_000) {
  const until = Date.now() + ms
  while (Date.now() < until) {
    if (await healthy(url)) return
    await new Promise((done) => setTimeout(done, 250))
  }
  throw new Error(`${url} did not answer in ${ms} ms`)
}

async function startServers() {
  if (await healthy('http://127.0.0.1:8000/health')) throw new Error('Port 8000 is busy: stop the backend or pass --base')
  const stub = spawn(process.execPath, [resolve(root, 'scripts/mock-backend.mjs')], { env: { ...process.env, STUB_CASE: 'status-skew' }, stdio: 'ignore' })
  const { createServer } = await import('vite')
  const vite = await createServer({ root, logLevel: 'silent', server: { host: '127.0.0.1', port: 5173, strictPort: true } })
  await vite.listen()
  await waitFor('http://127.0.0.1:8000/health')
  return {
    base: 'http://127.0.0.1:5173/',
    async close() {
      await vite.close()
      const exited = new Promise((done) => stub.once('exit', done))
      stub.kill()
      await exited
    },
  }
}

async function pausedDemo(page) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await page.getByRole('button', { name: 'Начать заново' }).click()
    await page.getByRole('button', { name: 'Пауза' }).click()
    const clock = await page.getByRole('banner').getByText(/\d\d:\d\d:\d\d/).textContent()
    if (clock?.includes('12:40:00')) return
  }
}

const MODES = {
  demo: { path: '?source=demo', ready: async (page) => { await page.getByRole('button', { name: 'Начать заново' }).waitFor(); await pausedDemo(page) } },
  live: { path: '', ready: async (page) => { await page.getByRole('banner').getByText('LIVE', { exact: true }).waitFor({ timeout: 15_000 }) } },
}

const servers = external ? null : await startServers()
const base = external ?? servers.base
const executablePath = process.env.PW_CHROMIUM_PATH || undefined
const browser = await chromium.launch({ executablePath, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] })
const shots = {}
try {
  for (const [mode, { path, ready }] of Object.entries(MODES)) {
    for (const width of WIDTHS) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: 'dark', deviceScaleFactor: 1, locale: 'ru-RU' })
      const page = await context.newPage()
      const errors = []
      page.on('pageerror', (error) => errors.push(error.message))
      await page.goto(new URL(path, base).href, { waitUntil: 'domcontentloaded' })
      await ready(page)
      await page.waitForTimeout(1_500)
      const audit = await page.evaluate(auditFn, { minFont: MIN_FONT_PX, minTarget: MIN_TARGET_PX })
      shots[`${mode}-${width}`] = { mode, width, errors, ...audit }
      await context.close()
    }
  }
} finally {
  await browser.close()
  await servers?.close()
}

const summary = Object.fromEntries(Object.entries(shots).map(([name, shot]) => [name, {
  lowContrast: shot.lowContrast.length,
  smallText: shot.smallText.length,
  smallTargets: shot.smallTargets.length,
  overflowPx: Math.max(0, shot.overflow.scrollWidth - shot.overflow.clientWidth),
  minContrast: shot.minContrast,
  pageErrors: shot.errors.length,
}]))
const violations = Object.values(summary).reduce((total, item) => total + item.lowContrast + item.smallText + item.smallTargets + (item.overflowPx > 0 ? 1 : 0), 0)
mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, JSON.stringify({ generatedAt: new Date().toISOString(), base, thresholds: { contrastAA: '4.5:1, 3:1 for large text', minFontPx: MIN_FONT_PX, minTargetPx: MIN_TARGET_PX }, violations, summary, shots }, null, 2))
console.table(summary)
console.log(`${violations} violation(s) · report: ${out}`)
if (strict && violations > 0) process.exit(1)
