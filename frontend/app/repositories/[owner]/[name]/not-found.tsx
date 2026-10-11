import Link from "next/link";

export default function RepositoryNotFound() {
  return (
    <main className="state-page">
      <div className="state-panel">
        <span className="error-code" aria-hidden="true">404</span>
        <p className="eyebrow">Repository not found</p>
        <h1>This repository isn’t tracked</h1>
        <p>It may have been renamed, transferred, or not discovered by Repovil yet.</p>
        <Link className="retry-button state-link" href="/?period=7d">Return to rankings</Link>
      </div>
    </main>
  );
}
