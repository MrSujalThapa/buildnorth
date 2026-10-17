export function PlaceholderPage({ title, copy }: { title: string; copy: string }) {
  return <section className="placeholder-page"><p className="eyebrow">PLAY IT OUT</p><h1>{title}</h1><p>{copy}</p></section>;
}
