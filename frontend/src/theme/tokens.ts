/** Resolved value of a design token from styles/tokens.css, for consumers that cannot use var() (MapLibre paint). */
export function cssToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
