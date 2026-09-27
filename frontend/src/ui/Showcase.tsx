import type { ReactNode } from 'react'
import { BellRing, Check, Info, Pause, RotateCcw, Send, TriangleAlert, Wifi, WifiOff, X } from 'lucide-react'
import { RISK, type RiskKey } from '../theme/risk'
import { Banner, Button, EmptyState, KeyValue, Panel, PanelHeader, RiskBadge, RiskMark, StatusDot, StatusPill, type BannerTone, type ButtonVariant, type StatusState } from '.'
import './showcase.css'

const risks: RiskKey[] = ['red', 'yellow', 'green', 'none']
const buttonVariants: ButtonVariant[] = ['primary', 'secondary', 'ghost', 'icon']
const buttonStates = ['default', 'hover', 'focus-visible', 'active', 'disabled', 'loading'] as const
const statuses: Array<[StatusState, string, ReactNode]> = [
  ['live', 'Поток', <Wifi size={14} />],
  ['demo', 'Replay', <Wifi size={14} />],
  ['waiting', 'Подключение', <WifiOff size={14} />],
  ['stale', 'Данные устарели', <WifiOff size={14} />],
  ['degraded', 'Деградация', <TriangleAlert size={14} />],
  ['offline', 'Нет связи', <WifiOff size={14} />],
]
const tones: Array<[BannerTone, string]> = [
  ['info', 'Демо-поток: положение бортов синтетическое.'],
  ['warning', 'Прогноз выдан более 2 минут назад. Проверьте актуальность перед действием.'],
  ['error', 'Живой поток недоступен. Повторное подключение выполняется автоматически.'],
  ['success', 'Отправлено водителю. Ответ водителя: «успеваю».'],
]
const colorTokens = ['--bg-canvas', '--surface-1', '--surface-2', '--line-subtle', '--line-control', '--text-primary', '--text-secondary', '--text-tertiary',
  '--accent', '--accent-hover', '--accent-tint', '--risk-red', '--risk-yellow', '--risk-green', '--risk-none',
  '--risk-red-tint', '--risk-yellow-tint', '--risk-green-tint', '--risk-none-tint']
const forecastRows = [
  { label: 'Прогноз отклонения', value: 'Опоздание 6:12' },
  { label: 'Диапазон q10–q90', value: '+5:00 – +7:35' },
  { label: 'Обновлён', value: '12:40:00' },
]

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="showcase-section" aria-label={title}><h2>{title}</h2>{children}</section>
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div className="showcase-row"><span className="showcase-label">{label}</span><div className="showcase-items">{children}</div></div>
}

function DemoButton({ variant, state }: { variant: ButtonVariant; state: typeof buttonStates[number] }) {
  const preview = state === 'hover' || state === 'focus-visible' || state === 'active' ? state : undefined
  const icon = variant === 'icon' ? <RotateCcw size={16} /> : <Send size={14} />
  return (
    <Button variant={variant} icon={icon} data-preview={preview} disabled={state === 'disabled' || state === 'loading'} loading={state === 'loading'}
      aria-label={variant === 'icon' ? `Начать заново (${state})` : undefined}>
      {variant === 'icon' ? null : state === 'loading' ? 'Отправка…' : 'Отправить'}
    </Button>
  )
}

/** Dev-only page (/?ui=1) with every primitive and state, for visual review and screenshots. */
export default function Showcase() {
  return (
    <main className="showcase">
      <h1>Витрина UI-примитивов</h1>
      <p className="showcase-lead">Только в dev-сборке: <code>/?ui=1</code>. Все цвета и размеры — токены из <code>styles/tokens.css</code>.</p>

      <Section title="Цветовые токены">
        <div className="showcase-swatches">
          {colorTokens.map((token) => <div key={token} className="showcase-swatch"><span style={{ background: `var(${token})` }} /><code>{token}</code></div>)}
        </div>
      </Section>

      <Section title="Button">
        {buttonVariants.map((variant) => (
          <Row key={variant} label={variant}>
            {buttonStates.map((state) => <div key={state} className="showcase-cell"><DemoButton variant={variant} state={state} /><small>{state}</small></div>)}
          </Row>
        ))}
        <Row label="aria-pressed">
          <div className="showcase-segmented"><Button variant="ghost" aria-pressed>Все</Button><Button variant="ghost" aria-pressed={false}>{RISK.red.label}</Button><Button variant="ghost" aria-pressed={false}>{RISK.yellow.label}</Button></div>
          <Button aria-pressed>Борт 131672 · выбран</Button>
          <Button variant="icon" aria-label="Пауза" icon={<Pause size={16} />} />
        </Row>
      </Section>

      <Section title="RiskBadge и RiskMark">
        <Row label="badge">{risks.map((risk) => <RiskBadge key={risk} risk={risk} />)}</Row>
        <Row label="mark (icon)">{risks.map((risk) => <span key={risk} className="showcase-inline"><RiskMark risk={risk} />{RISK[risk].label}</span>)}</Row>
        <Row label="marker">{risks.map((risk) => <span key={risk} className="showcase-inline"><RiskMark variant="marker" risk={risk} />{RISK[risk].label}</span>)}</Row>
        <div className="showcase-stack">{risks.map((risk) => <RiskBadge key={risk} variant="strip" risk={risk} value={risk === 'none' ? '—' : '+6:12'} />)}</div>
      </Section>

      <Section title="StatusPill и StatusDot">
        <Row label="pill">{statuses.map(([state, text, icon]) => <StatusPill key={state} state={state} icon={icon}>{text}</StatusPill>)}</Row>
        <Row label="dot">{statuses.map(([state, text]) => <span key={state} className="showcase-inline"><StatusDot state={state} />{text}</span>)}</Row>
      </Section>

      <Section title="Banner">
        {tones.map(([tone, text]) => <Banner key={tone} tone={tone} icon={<Info size={16} />} action={tone === 'error' ? <Button>Вернуться в демо</Button> : undefined}>{text}</Banner>)}
        <div className="showcase-stack">
          {tones.map(([tone, text]) => <Banner key={tone} tone={tone} inset icon={tone === 'success' ? <Check size={14} /> : tone === 'error' ? <X size={14} /> : <Info size={14} />}>{text}</Banner>)}
        </div>
      </Section>

      <Section title="KeyValue">
        <div className="showcase-grid">
          <div><small>row</small><KeyValue rows={forecastRows} /></div>
          <div><small>row · stale</small><KeyValue rows={forecastRows} stale /></div>
          <div><small>dense</small><KeyValue variant="dense" rows={forecastRows} /></div>
        </div>
      </Section>

      <Section title="Panel, PanelHeader и EmptyState">
        <div className="showcase-grid">
          <Panel className="showcase-panel" aria-label="Панель с данными">
            <PanelHeader eyebrow="Очередь диспетчера" title="Предупреждения" actions={<span className="count-badge">3</span>} />
            <Panel as="div" variant="inset" className="showcase-inset">Вложенная поверхность (inset)</Panel>
          </Panel>
          <Panel className="showcase-panel" aria-label="Пустая панель">
            <PanelHeader eyebrow="Детали события" title="Карточка борта" />
            <EmptyState icon={<BellRing size={28} />} title="Активных предупреждений нет" hint="Новые предупреждения появятся здесь." />
          </Panel>
          <Panel className="showcase-panel" aria-label="Загрузка" busy>
            <PanelHeader title="Загрузка" compact icon={<Info size={17} />}><span>Ожидаем снимок</span></PanelHeader>
            <EmptyState title="Ожидаем данные" hint="Лента появится после получения снимка." action={<Button variant="ghost">Вернуться в демо</Button>} />
          </Panel>
          <div className="showcase-overlay-host"><EmptyState variant="overlay" icon={<BellRing size={28} />} title="Бортов в снимке нет" hint="Текущий снимок содержит пустой список бортов." /></div>
        </div>
      </Section>
    </main>
  )
}
