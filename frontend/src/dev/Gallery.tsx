import type { ReactNode } from 'react'
import '../styles/global.css'
import styles from './Gallery.module.css'

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
    <main className={styles.page}>
      <h1 className={styles.title}>Fixture gallery</h1>
      <nav aria-label="Gallery sections" className={styles.nav}>
        {entries.map(({ id, entry }) => (
          <a key={id} href={`#${id}`} className={styles.link}>
            {entry.title}
          </a>
        ))}
      </nav>
      {entries.map(({ id, entry }) => (
        <section key={id} id={id} aria-labelledby={`${id}-title`} className={styles.section}>
          <h2 id={`${id}-title`} className={styles.sectionTitle}>
            {entry.title}
          </h2>
          {entry.render()}
        </section>
      ))}
    </main>
  )
}
