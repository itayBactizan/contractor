import { useState } from 'react'
import ByIdView from './components/ByIdView.jsx'
import CategoryView from './components/CategoryView.jsx'
import DatasetView from './components/DatasetView.jsx'
import './App.css'

const TABS = [
  { id: 'by-id', label: 'By ID' },
  { id: 'by-category', label: 'By category' },
  { id: 'dataset', label: 'Dataset (YOLO)' },
]

export default function App() {
  const [tab, setTab] = useState('by-id')

  return (
    <main className="app">
      <h1>Contract Orthophoto</h1>

      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`tab ${tab === t.id ? 'tab-active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Both views stay mounted, so switching tabs keeps their inputs and results */}
      <div hidden={tab !== 'by-id'}>
        <ByIdView />
      </div>
      <div hidden={tab !== 'by-category'}>
        <CategoryView />
      </div>
      <div hidden={tab !== 'dataset'}>
        <DatasetView />
      </div>
    </main>
  )
}
