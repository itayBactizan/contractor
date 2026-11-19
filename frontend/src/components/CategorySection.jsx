import { useEffect, useState } from 'react'
import ImageCard from './ImageCard.jsx'

const COUNT = 5
// The <select> needs a string; null (empty field) gets this placeholder key
const NULL_KEY = '__null__'

const toKey = (value) => (value === null ? NULL_KEY : value)
const fromKey = (key) => (key === NULL_KEY ? null : key)
const fileName = (url) => url.split('?')[0].split('/').pop()

// One section: field -> value -> N random images. Used by the "By category" and "Dataset" tabs.
// props: layer ("contracts" | "plots"), title, kind ("contract" | "plot"), fields (allowed field names),
//        sampleUrl (endpoint that creates the images), onResults (called with each server answer),
//        idPrefix (unique HTML ids when the same layer appears in two tabs)
export default function CategorySection({
  layer,
  title,
  kind,
  fields,
  sampleUrl = '/api/categories/sample',
  onResults,
  idPrefix = layer,
}) {
  const [field, setField] = useState(fields[0])
  const [options, setOptions] = useState([]) // [{ value, count }]
  const [optionsState, setOptionsState] = useState('loading') // 'loading' | 'ready' | 'error'
  const [selected, setSelected] = useState('') // key of the chosen value

  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState(null) // { total_matches, images, failed }
  const [error, setError] = useState('')

  // Load the field's values whenever the field changes (like re-running value_counts)
  useEffect(() => {
    let cancelled = false // ignore a late answer if the field changed meanwhile
    fetch(`/api/categories/${layer}/${field}/values`)
      .then((response) => {
        if (!response.ok) throw new Error(`Server error ${response.status}`)
        return response.json()
      })
      .then((data) => {
        if (cancelled) return
        setOptions(data)
        setOptionsState('ready')
      })
      .catch(() => {
        if (!cancelled) setOptionsState('error')
      })
    return () => {
      cancelled = true
    }
  }, [layer, field])

  // A new field means new values: reset the choice and results, then the effect loads values
  function changeField(newField) {
    setField(newField)
    setOptionsState('loading')
    setSelected('')
    setResults(null)
  }

  async function getImages() {
    setLoading(true)
    setError('')
    try {
      const response = await fetch(sampleUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layer, field, value: fromKey(selected), count: COUNT }),
      })
      if (!response.ok) throw new Error(`Server error ${response.status}`)
      const data = await response.json()
      setResults(data)
      if (onResults) onResults(data)
    } catch (err) {
      setError(`Could not get images: ${err.message}. Is the API server running?`)
    } finally {
      setLoading(false)
    }
  }

  const selectedOption = options.find((o) => toKey(o.value) === selected)

  return (
    <section className={`box box-${kind} category-section`}>
      <h2>{title}</h2>

      {fields.length > 1 ? (
        <>
          <label htmlFor={`${idPrefix}-field`}>Field</label>
          <select id={`${idPrefix}-field`} value={field} onChange={(e) => changeField(e.target.value)}>
            {fields.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </>
      ) : (
        <p className="field-name">
          Field: <strong>{field}</strong>
        </p>
      )}

      <label htmlFor={`${idPrefix}-value`}>Value</label>
      <select
        id={`${idPrefix}-value`}
        value={selected}
        onChange={(e) => {
          setSelected(e.target.value)
          setResults(null)
        }}
        disabled={optionsState !== 'ready'}
      >
        <option value="">
          {optionsState === 'loading' && 'Loading values…'}
          {optionsState === 'error' && 'Could not load values'}
          {optionsState === 'ready' && `Choose a value (${options.length} options)`}
        </option>
        {options.map((o) => (
          <option key={toKey(o.value)} value={toKey(o.value)}>
            {o.value === null ? '(empty)' : o.value}
            {o.count !== null ? ` (${o.count})` : ''}
          </option>
        ))}
      </select>

      <div className="form-actions">
        <button className="button" type="button" onClick={getImages} disabled={!selected || loading}>
          {loading ? 'Loading…' : results ? `Get ${COUNT} more` : `Get ${COUNT} random images`}
        </button>
        {selectedOption && selectedOption.count !== null && (
          <span className="hint">{selectedOption.count} matching</span>
        )}
      </div>

      {loading && <p className="status">Creating {COUNT} images… this can take a few seconds per image.</p>}
      {error && <p className="banner">{error}</p>}

      {results && (
        <p className="status">
          {results.contracts_added !== undefined
            ? `Added ${results.contracts_added} contracts (${results.images.length} images) of ${results.total_matches} matching.`
            : `Showing ${results.images.length} random of ${results.total_matches} matching.`}
        </p>
      )}

      {results && results.images.length > 0 && (
        <div className="grid grid-compact">
          {results.images.map((image) => (
            <ImageCard
              key={image.image_url}
              title={image.label}
              imageUrl={image.image_url}
              downloadName={fileName(image.image_url)}
            >
              <span className={`card-detail detail-${kind}`}>{image.attributes[field] ?? '(empty)'}</span>
            </ImageCard>
          ))}
        </div>
      )}

      {results && results.failed.length > 0 && (
        <details className="failed">
          <summary>Skipped {results.failed.length} (replaced by other random items)</summary>
          <ul>
            {results.failed.map((item) => (
              <li key={item.id}>
                <strong>{item.id}</strong>: {item.error}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
