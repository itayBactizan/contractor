// The chosen items of one kind, each with a × button to remove it.
export default function ChipList({ items, kind, labelFor, onRemove }) {
  if (items.length === 0) {
    return <p className="chips-empty">None added yet.</p>
  }
  return (
    <ul className="chips">
      {items.map((item, index) => (
        <li key={labelFor(item)} className={`chip chip-${kind}`}>
          <span>{labelFor(item)}</span>
          <button type="button" onClick={() => onRemove(index)} aria-label={`Remove ${labelFor(item)}`}>
            ×
          </button>
        </li>
      ))}
    </ul>
  )
}
