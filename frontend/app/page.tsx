import Link from "next/link";

import {
  fetchCategories,
  fetchRankings,
  type Category,
  type RankingItem,
  type RankingsResponse,
} from "../lib/api";
import {
  buildRankingHref,
  parseRankingQuery,
  PERIODS,
  type RankingQuery,
  type SearchParams,
} from "../lib/ranking-query";

export const dynamic = "force-dynamic";

type HomeProps = {
  searchParams?: Promise<SearchParams>;
};

const numberFormatter = new Intl.NumberFormat("en-US");
const dateFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  timeZoneName: "short",
});

function FilterLink({
  href,
  selected,
  children,
}: {
  href: string;
  selected: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link className="filter-link" href={href} aria-current={selected ? "page" : undefined}>
      {children}
    </Link>
  );
}

function Filters({ categories, query }: { categories: Category[]; query: RankingQuery }) {
  return (
    <section className="filters" aria-label="Ranking filters">
      <div className="filter-group">
        <span className="filter-label" id="period-filter-label">
          Window
        </span>
        <nav className="filter-options" aria-labelledby="period-filter-label">
          {PERIODS.map((period) => (
            <FilterLink
              key={period}
              href={buildRankingHref({ ...query, period, page: 1 })}
              selected={query.period === period}
            >
              {period}
            </FilterLink>
          ))}
        </nav>
      </div>

      <div className="filter-group category-filter">
        <span className="filter-label" id="category-filter-label">
          Category
        </span>
        <nav className="filter-options" aria-labelledby="category-filter-label">
          <FilterLink
            href={buildRankingHref({ ...query, category: undefined, page: 1 })}
            selected={query.category === undefined}
          >
            All
          </FilterLink>
          {categories.map((category) => (
            <FilterLink
              key={category.slug}
              href={buildRankingHref({ ...query, category: category.slug, page: 1 })}
              selected={query.category === category.slug}
            >
              {category.name}
            </FilterLink>
          ))}
        </nav>
      </div>
    </section>
  );
}

function RepositoryCard({ item, position }: { item: RankingItem; position: number }) {
  const detailHref = `/repositories/${encodeURIComponent(item.owner)}/${encodeURIComponent(item.name)}`;

  return (
    <article className="repository-card">
      <div className="rank" aria-label={`Rank ${position}`}>
        {String(position).padStart(2, "0")}
      </div>
      <div className="repository-main">
        <div className="repository-heading">
          <div>
            <Link className="repository-name" href={detailHref}>
              <span>{item.owner}/</span>
              {item.name}
            </Link>
            {item.is_estimated ? <span className="estimated-badge">Estimated</span> : null}
          </div>
          <a
            className="github-link"
            href={item.github_url}
            target="_blank"
            rel="noreferrer"
            aria-label={`Open ${item.owner}/${item.name} on GitHub (opens in a new tab)`}
          >
            GitHub <span aria-hidden="true">↗</span>
          </a>
        </div>
        <p className="repository-description">
          {item.description ?? "No description provided."}
        </p>
        <div className="repository-meta">
          {item.language ? <span className="language">{item.language}</span> : null}
          {item.categories.map((category) => (
            <span className="category-chip" key={category.slug}>
              {category.name}
            </span>
          ))}
        </div>
      </div>
      <dl className="metrics">
        <div>
          <dt>Stars</dt>
          <dd>{numberFormatter.format(item.current_stars)}</dd>
        </div>
        <div>
          <dt>Star gain</dt>
          <dd className="positive">+{numberFormatter.format(item.star_gain)}</dd>
        </div>
        <div>
          <dt>Growth score</dt>
          <dd>{item.score.toFixed(4)}</dd>
        </div>
      </dl>
    </article>
  );
}

function EmptyState({ state }: Pick<RankingsResponse, "state">) {
  if (state === "preparing") {
    return (
      <section className="empty-state" aria-live="polite">
        <span className="status-mark" aria-hidden="true">
          ···
        </span>
        <h2>Ranking data is being prepared</h2>
        <p>The first tracking run has not been published yet. Check back after collection.</p>
      </section>
    );
  }

  return (
    <section className="empty-state" aria-live="polite">
      <span className="status-mark" aria-hidden="true">
        0
      </span>
      <h2>No repositories match these filters</h2>
      <p>Try another period or category. Active categories remain available above.</p>
    </section>
  );
}

function Pagination({ response, query }: { response: RankingsResponse; query: RankingQuery }) {
  const { page, total_pages: totalPages } = response.pagination;
  if (totalPages <= 1 && page <= 1) {
    return null;
  }

  const hasPrevious = page > 1;
  const hasNext = page < totalPages;

  return (
    <nav className="pagination" aria-label="Ranking pages">
      {hasPrevious ? (
        <Link className="page-link" href={buildRankingHref({ ...query, page: page - 1 })}>
          <span aria-hidden="true">←</span> Previous
        </Link>
      ) : (
        <span className="page-link disabled">← Previous</span>
      )}
      <span className="page-position">
        Page <strong>{page}</strong>
        {totalPages > 0 ? ` of ${totalPages}` : ""}
      </span>
      {hasNext ? (
        <Link className="page-link" href={buildRankingHref({ ...query, page: page + 1 })}>
          Next <span aria-hidden="true">→</span>
        </Link>
      ) : (
        <span className="page-link disabled">Next →</span>
      )}
    </nav>
  );
}

export function RankingPage({
  categories,
  rankings,
  query,
}: {
  categories: Category[];
  rankings: RankingsResponse;
  query: RankingQuery;
}) {
  return (
    <>
      <a className="skip-link" href="#ranking-results">
        Skip to ranking results
      </a>
      <header className="site-header">
        <Link className="wordmark" href="/?period=7d" aria-label="Repovil home">
          <span className="wordmark-mark" aria-hidden="true">
            R
          </span>
          REP<span>O</span>VIL
        </Link>
        <p>AI open-source momentum index</p>
      </header>

      <main>
        <section className="hero">
          <p className="eyebrow">Open-source signal / updated every 6 hours</p>
          <h1>
            Find the AI projects
            <br />
            <em>gaining momentum.</em>
          </h1>
          <p className="hero-copy">
            Repositories ranked by recent star growth—not lifetime popularity. Surface what is
            moving before it becomes obvious.
          </p>
        </section>

        <Filters categories={categories} query={query} />

        <section id="ranking-results" className="ranking-section" aria-labelledby="ranking-title">
          <div className="ranking-header">
            <div>
              <p className="section-kicker">Live ranking</p>
              <h2 id="ranking-title">Momentum leaders</h2>
            </div>
            {rankings.state === "ready" && rankings.calculated_at ? (
              <p className="updated-at">
                Published{" "}
                <time dateTime={rankings.calculated_at}>
                  {dateFormatter.format(new Date(rankings.calculated_at))}
                </time>
              </p>
            ) : null}
          </div>

          {rankings.items.length > 0 ? (
            <div className="repository-list">
              {rankings.items.map((item, index) => (
                <RepositoryCard
                  key={item.github_id}
                  item={item}
                  position={
                    (rankings.pagination.page - 1) * rankings.pagination.page_size + index + 1
                  }
                />
              ))}
            </div>
          ) : (
            <EmptyState state={rankings.state} />
          )}

          <Pagination response={rankings} query={query} />
        </section>
      </main>

      <footer>
        <span>Repovil</span>
        <span>Public GitHub data · Read-only</span>
      </footer>
    </>
  );
}

export default async function Home({ searchParams = Promise.resolve({}) }: HomeProps) {
  const query = parseRankingQuery(await searchParams);
  const [categories, rankings] = await Promise.all([
    fetchCategories(),
    fetchRankings(query),
  ]);

  return <RankingPage categories={categories} rankings={rankings} query={query} />;
}
