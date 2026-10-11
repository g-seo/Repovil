export default function Loading() {
  return (
    <main className="state-page" aria-live="polite" aria-busy="true">
      <div className="state-panel">
        <span className="loader" aria-hidden="true" />
        <p className="eyebrow">Refreshing signal</p>
        <h1>Loading momentum data</h1>
        <p>Fetching the latest published ranking from Repovil.</p>
      </div>
    </main>
  );
}
