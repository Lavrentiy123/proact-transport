import { describe, expect, it } from 'vitest'
import { pickAxisLabels, type AxisTick } from './track'

const WIDTH = 38
const GAP = 8

function minuteTicks(count: number, step: number, from = 60): AxisTick[] {
  return Array.from({ length: count }, (_, index) => ({ x: from + index * step, text: `07:${String(10 + index).padStart(2, '0')}` }))
}

function assertSeparated(ticks: AxisTick[], picked: number[]) {
  for (let index = 1; index < picked.length; index++) {
    expect(ticks[picked[index]].x - ticks[picked[index - 1]].x).toBeGreaterThanOrEqual(WIDTH + GAP)
  }
}

describe('pickAxisLabels', () => {
  it('thins dense stops so neighbouring boxes never meet', () => {
    const ticks = minuteTicks(40, 12)
    const picked = pickAxisLabels(ticks, WIDTH, GAP)
    assertSeparated(ticks, picked)
    expect(picked.length).toBeGreaterThanOrEqual(9)
  })

  it('shows a repeated clock text only once', () => {
    const ticks: AxisTick[] = [
      { x: 60, text: '07:17' }, { x: 120, text: '07:17' }, { x: 180, text: '07:18' }, { x: 240, text: '07:18' }, { x: 300, text: '07:19' },
    ]
    const picked = pickAxisLabels(ticks, WIDTH, GAP)
    expect(picked.map((index) => ticks[index].text)).toEqual(['07:17', '07:18', '07:19'])
  })

  it('keeps the first and last labels and drops their close neighbours', () => {
    const ticks = minuteTicks(10, 30)
    const picked = pickAxisLabels(ticks, WIDTH, GAP, [0, 9])
    expect(picked[0]).toBe(0)
    expect(picked.at(-1)).toBe(9)
    expect(picked).not.toContain(8)
    assertSeparated(ticks, picked)
  })

  it('prefers the target stop over a neighbour that would collide with it', () => {
    const ticks = minuteTicks(10, 30)
    const picked = pickAxisLabels(ticks, WIDTH, GAP, [0, 9, 5])
    expect(picked).toContain(5)
    expect(picked).not.toContain(4)
    expect(picked).not.toContain(6)
    assertSeparated(ticks, picked)
  })

  it('leaves at most the ends on a narrow phone plot', () => {
    expect(pickAxisLabels(minuteTicks(15, 5), WIDTH, GAP, [0, 14])).toEqual([0, 14])
    expect(pickAxisLabels(minuteTicks(15, 2), WIDTH, GAP, [0, 14])).toEqual([0])
  })
})
