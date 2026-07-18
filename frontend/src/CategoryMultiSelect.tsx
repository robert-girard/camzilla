import { useId, useMemo, useState } from 'react'

import type { CatalogCategory } from './types'

type Props = {
  label: string
  categories: CatalogCategory[]
  selectedIds: string[]
  onChange: (categoryIds: string[]) => void
  disabled?: boolean
}

export function CategoryMultiSelect({ label, categories, selectedIds, onChange, disabled }: Props) {
  const id = useId()
  const [query, setQuery] = useState('')
  const known = useMemo(
    () => new Map(categories.map((category) => [category.semantic_id, category])),
    [categories],
  )
  const unavailable = selectedIds.filter((categoryId) => !known.has(categoryId))
  const filtered = categories.filter((category) => {
    const needle = query.trim().toLocaleLowerCase()
    return !needle || `${category.display_label} ${category.semantic_id} ${category.description ?? ''}`
      .toLocaleLowerCase().includes(needle)
  })

  const toggle = (categoryId: string, checked: boolean) => {
    const next = checked
      ? [...new Set([...selectedIds, categoryId])]
      : selectedIds.filter((item) => item !== categoryId)
    onChange(next)
  }

  const selectAll = () => onChange([
    ...new Set([...selectedIds, ...filtered.map((category) => category.semantic_id)]),
  ])

  return (
    <fieldset className="category-select" disabled={disabled} aria-describedby={`${id}-count`}>
      <legend>{label}</legend>
      <div className="category-toolbar">
        <label htmlFor={`${id}-search`}>Search categories</label>
        <input
          id={`${id}-search`}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <button type="button" onClick={selectAll} disabled={filtered.length === 0}>Select all</button>
        <button type="button" onClick={() => onChange([])}>Clear</button>
      </div>
      <p id={`${id}-count`} className="category-count">
        {selectedIds.length} active of {categories.length} available
      </p>
      {unavailable.map((categoryId) => (
        <label key={categoryId} className="category-option unavailable">
          <input
            type="checkbox"
            checked
            onChange={(event) => toggle(categoryId, event.target.checked)}
          />
          <span><strong>{categoryId}</strong><small>Unavailable in this catalog; remove explicitly.</small></span>
        </label>
      ))}
      <div className="category-options">
        {filtered.map((category) => (
          <label key={category.semantic_id} className="category-option">
            <input
              type="checkbox"
              checked={selectedIds.includes(category.semantic_id)}
              onChange={(event) => toggle(category.semantic_id, event.target.checked)}
            />
            <span>
              <strong>{category.display_label}</strong>
              <small>{category.description ?? category.semantic_id}</small>
            </span>
          </label>
        ))}
        {filtered.length === 0 && <p>No categories match this search.</p>}
      </div>
      <div className="category-preview" aria-label={`${label} preview`}>
        <strong>Selection preview:</strong>{' '}
        {selectedIds.length
          ? selectedIds.map((categoryId) => known.get(categoryId)?.display_label ?? categoryId).join(', ')
          : 'none selected'}
      </div>
    </fieldset>
  )
}
