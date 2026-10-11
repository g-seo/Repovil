import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  ApiError,
  fetchRepository,
  fetchStarHistory,
  type Repository,
  type StarHistoryResponse,
} from "../../../../lib/api";
import { StarHistoryGraph } from "./star-history-graph";

export const dynamic = "force-dynamic";

type DetailRouteProps = {
  params: Promise<{ owner: string; name: string }>;
};

const numberFormatter = new Intl.NumberFormat("en-US");
const dateFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

export const metadata: Metadata = {
  title: "Repository details — Repovil",
  description: "Repository metadata and 30-day star history.",
};

function SiteHeader() {
  return (
    <header className="site-header">
      <Link className="wordmark" href="/?period=7d" aria-label="Repovil home">
        <span className="wordmark-mark" aria-hidden="true">R</span>
        REP<span>O</span>VIL
      </Link>
      <p>AI open-source momentum index</p>
    </header>
  );
}

export function RepositoryDetailPage({
  repository,
  history,
  now,
}: {
  repository: Repository;
  history: StarHistoryResponse;
  now: Date;
}) {
  return (
    <>
      <a className="skip-link" href="#repository-history">Skip to star history</a>
      <SiteHeader />
      <main>
        <nav className="detail-breadcrumb" aria-label="Breadcrumb">
          <Link href="/?period=7d">Rankings</Link>
          <span aria-hidden="true">/</span>
          <span aria-current="page">Repository</span>
        </nav>

        <article className="detail-hero">
          <div className="detail-title">
            <p className="eyebrow">Repository profile</p>
            <h1><span>{repository.owner}/</span>{repository.name}</h1>
            <p className="detail-description">
              {repository.description ?? "No description provided."}
            </p>
            <div className="repository-meta">
              {repository.language ? <span className="language">{repository.language}</span> : null}
              {repository.categories.map((category) => (
                <span className="category-chip" key={category.slug}>{category.name}</span>
              ))}
              {repository.status !== "active" ? (
                <span className="repository-status">{repository.status.replace("_", " ")}</span>
              ) : null}
            </div>
          </div>
          <div className="detail-facts">
            <dl>
              <div><dt>Current stars</dt><dd>{numberFormatter.format(repository.current_stars)}</dd></div>
              <div><dt>Discovered</dt><dd>{dateFormatter.format(new Date(repository.discovered_at))}</dd></div>
              <div>
                <dt>Tracking since</dt>
                <dd>{repository.tracking_started_at ? dateFormatter.format(new Date(repository.tracking_started_at)) : "Pending"}</dd>
              </div>
            </dl>
            <a
              className="detail-github-link"
              href={repository.github_url}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open ${repository.owner}/${repository.name} on GitHub (opens in a new tab)`}
            >
              View on GitHub <span aria-hidden="true">↗</span>
            </a>
          </div>
        </article>

        <section id="repository-history" className="history-section">
          <StarHistoryGraph points={history.points} now={now} />
        </section>
      </main>
      <footer><span>Repovil</span><span>Public GitHub data · Read-only</span></footer>
    </>
  );
}

export default async function RepositoryDetailRoute({ params }: DetailRouteProps) {
  const requestedAt = new Date();
  const { owner, name } = await params;
  let repository: Repository;
  let history: StarHistoryResponse;
  try {
    [repository, history] = await Promise.all([
      fetchRepository(owner, name),
      fetchStarHistory(owner, name),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }
  return <RepositoryDetailPage repository={repository} history={history} now={requestedAt} />;
}
