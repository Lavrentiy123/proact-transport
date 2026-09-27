import React, { lazy, Suspense } from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource/inter/latin-400.css'
import '@fontsource/inter/cyrillic-400.css'
import '@fontsource/inter/latin-500.css'
import '@fontsource/inter/cyrillic-500.css'
import '@fontsource/inter/latin-600.css'
import '@fontsource/inter/cyrillic-600.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/cyrillic-400.css'
import '@fontsource/jetbrains-mono/latin-500.css'
import '@fontsource/jetbrains-mono/cyrillic-500.css'
import App from './App'
import './styles.css'

// Primitives showcase for visual review: dev server only, /?ui=1. The production build drops it.
const showcase = import.meta.env.DEV && new URLSearchParams(window.location.search).get('ui') === '1'
const Root = showcase ? lazy(() => import('./ui/Showcase')) : App

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Suspense fallback={null}><Root /></Suspense>
  </React.StrictMode>,
)
