import { useState } from 'react'
import ChipList from './ChipList.jsx'
import ImageCard from './ImageCard.jsx'

// "111, 222 333" -> ["111", "222", "333"]
function splitIds(text) {
  return text.split(/[\s,]+/).filter(Boolean)
}

const plotLabel = (plot) => (plot.tochnit ? `${plot.tochnit} / ${plot.migrash}` : plot.migrash)

// "/images/combined_x.png?t=1" -> "combined_x.png"
const fileName = (url) => url.split('?')[0].split('/').pop()

// "By ID" tab: chosen contracts and plots on combined images (nearby items share an image)
export default function ByIdView() {
  const [contractText, setContractText] = useState('')
  const [tochnitText, setTochnitText] = useState('')
  const [migrashText, setMigrashText] = useState('')
  const [contracts, setContracts] = useState([]) // ["900395618", ...]
  const [plots, setPlots] = useState([]) // [{ migrash, tochnit }, ...]

  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState(null) // { images: [...], failed: [...] }
  const [error, setError] = useState('')

  function addContracts() {
    const ids = splitIds(contractText).filter((id) => !contracts.includes(id))
    setContracts([...contracts, ...ids])
    setContractText('')
  }

  function addPlots() {
    const tochnit = tochnitText.trim() || null
    const labels = new Set(plots.map(plotLabel))
    const added = splitIds(migrashText)
      .map((migrash) => ({ migrash, tochnit }))
      .filter((plot) => !labels.has(plotLabel(plot)))
    setPlots([...plots, ...added])
    setMigrashText('')
  }

  // Enter in an input = press that box's Add button
  const onEnter = (action) => (event) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      action()
    }
  }

  async function createImage() {
    setLoading(true)
    setError('')
    setResults(null)
    try {
      const response = await fetch('/api/combined', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contract_ids: contracts, plots }),
      })
      if (!response.ok) throw new Error(`Server error ${response.status}`)
      setResults(await response.json())
    } catch (err) {
      setError(`Could not create the image: ${err.message}. Is the API server running?`)
    } finally {
      setLoading(false)
    }
  }

  const nothingChosen = contracts.length === 0 && plots.length === 0

  return (
    <>
      <p className="subtitle">
        Add contracts and plots, then create an orthophoto with contracts in red and plots in blue.
      </p>

      <div className="boxes">
        <section className="box box-contract">
          <h2>Contracts</h2>
          <label htmlFor="contract-ids">Contract IDs</label>
          <div className="input-row">
            <input
              id="contract-ids"
              value={contractText}
              onChange={(e) => setContractText(e.target.value)}
              onKeyDown={onEnter(addContracts)}
              placeholder="900395618, 900058139"
            />
            <button className="button" type="button" onClick={addContracts} disabled={!contractText.trim()}>
              Add contracts
            </button>
          </div>
          <ChipList
            items={contracts}
            kind="contract"
            labelFor={(id) => id}
            onRemove={(i) => setContracts(contracts.filter((_, j) => j !== i))}
          />
        </section>

        <section className="box box-plot">
          <h2>Plots</h2>
          <label htmlFor="tochnit">Plan (TOCHNIT), optional</label>
          <input
            id="tochnit"
            value={tochnitText}
            onChange={(e) => setTochnitText(e.target.value)}
            onKeyDown={onEnter(addPlots)}
            placeholder="Leave empty to search all plans"
          />
          <label htmlFor="migrash">Plot numbers (MIGRASH)</label>
          <div className="input-row">
            <input
              id="migrash"
              value={migrashText}
              onChange={(e) => setMigrashText(e.target.value)}
              onKeyDown={onEnter(addPlots)}
              placeholder="12, 13"
            />
            <button className="button" type="button" onClick={addPlots} disabled={!migrashText.trim()}>
              Add plots
            </button>
          </div>
          <ChipList
            items={plots}
            kind="plot"
            labelFor={plotLabel}
            onRemove={(i) => setPlots(plots.filter((_, j) => j !== i))}
          />
        </section>
      </div>

      <div className="create-row">
        <button className="button button-large" type="button" onClick={createImage} disabled={loading || nothingChosen}>
          {loading ? 'Creating…' : 'Create image'}
        </button>
        <span className="legend">
          <span className="swatch swatch-contract" /> Contract
          <span className="swatch swatch-plot" /> Plot
        </span>
      </div>

      {loading && (
        <p className="status">Creating the image… this can take a few seconds per contract and plot.</p>
      )}

      {error && <p className="banner">{error}</p>}

      {results && results.images.length === 0 && results.failed.length === 0 && (
        <p className="status">No results.</p>
      )}

      {results && results.images.length > 1 && (
        <p className="status">
          The items are far apart, so they were split into {results.images.length} images by location.
        </p>
      )}

      {results && results.images.length > 0 && (
        <section className="grid">
          {results.images.map((image, n) => (
            <ImageCard
              key={image.image_url}
              title={results.images.length > 1 ? `Image ${n + 1}` : 'Combined image'}
              imageUrl={image.image_url}
              downloadName={fileName(image.image_url)}
            >
              {image.contracts.length > 0 && (
                <span className="card-detail detail-contract">Contracts: {image.contracts.join(', ')}</span>
              )}
              {image.plots.length > 0 && (
                <span className="card-detail detail-plot">Plots: {image.plots.join(', ')}</span>
              )}
            </ImageCard>
          ))}
        </section>
      )}

      {results && results.failed.length > 0 && (
        <section className="failed">
          <h2>Failed ({results.failed.length})</h2>
          <ul>
            {results.failed.map((item) => (
              <li key={`${item.type}-${item.id}`}>
                <strong>
                  {item.type === 'plot' ? 'Plot' : 'Contract'} {item.id}
                </strong>
                : {item.error}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
