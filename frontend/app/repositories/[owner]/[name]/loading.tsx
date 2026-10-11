export default function RepositoryLoading() {
  return (
    <main className="state-page" aria-live="polite" aria-busy="true">
      <div className="state-panel">
        <span className="loader" aria-hidden="true" />
        <p className="eyebrow">Loading repository</p>
        <h1>Building the star timeline</h1>
        <p>Fetching stored metadata and the latest 30-day history from Repovil.</p>
      </div>
    </main>
  );
}
