"use client";

export default function RepositoryError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="state-page">
      <div className="state-panel" role="alert">
        <span className="error-code" aria-hidden="true">!</span>
        <p className="eyebrow">Connection interrupted</p>
        <h1>We couldn’t load this repository</h1>
        <p>The stored repository data is temporarily unavailable. Retry the request in a moment.</p>
        <button type="button" className="retry-button" onClick={reset}>Try again</button>
        {error.digest ? <small>Reference: {error.digest}</small> : null}
      </div>
    </main>
  );
}
