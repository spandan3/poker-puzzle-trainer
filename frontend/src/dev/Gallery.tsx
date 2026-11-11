import type { ReactNode } from 'react'
import '../styles/global.css'

export interface GalleryEntry {
  title: string
  render: () => ReactNode
}

// Each file in ./entries default-exports `{ title, render }`, so parallel tasks add files
// without editing this one.
const modules = import.meta.glob<{ default?: GalleryEntry }>('./entries/*.tsx', { eager: true })

const entries: { id: string; entry: GalleryEntry }[] = Object.entries(modules)
  .flatMap(([path, mod]) => {
    const entry = mod.default
    return entry ? [{ id: path.replace(/^\.\/entries\/|\.tsx$/g, ''), entry }] : []
  })
  .sort((a, b) => a.id.localeCompare(b.id))

export default function Gallery() {
  return (
    <main style={{ padding: 'var(--space-6)', maxWidth: 1200, margin: '0 auto' }}>
      <h1>Fixture gallery</h1>
      <nav aria-label="Gallery sections" style={{ display: 'flex', gap: 'var(--space-4)' }}>
        {entries.map(({ id, entry }) => (
          <a key={id} href={`#${id}`} style={{ color: 'var(--color-accent)' }}>
            {entry.title}
          </a>
        ))}
      </nav>
      {entries.map(({ id, entry }) => (
        <section
          key={id}
          id={id}
          aria-labelledby={`${id}-title`}
          style={{ marginTop: 'var(--space-6)' }}
        >
          <h2 id={`${id}-title`}>{entry.title}</h2>
          {entry.render()}
        </section>
      ))}
    </main>
  )
}
