import type { StarHistoryPoint } from "../../../../lib/api";

const WINDOW_MS = 30 * 24 * 60 * 60 * 1000;
const WIDTH = 760;
const HEIGHT = 300;
const PLOT = { left: 58, right: 742, top: 22, bottom: 248 };

const starFormatter = new Intl.NumberFormat("en-US");
const dateFormatter = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});
const accessibleDateFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "long",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
  timeZoneName: "short",
});

type PlottedPoint = StarHistoryPoint & {
  timestamp: number;
  x: number;
  y: number;
};

function utcDate(timestamp: number): string {
  return new Date(timestamp).toISOString().slice(0, 10);
}

export function recentHistoryPoints(
  points: StarHistoryPoint[],
  now: Date,
): Array<StarHistoryPoint & { timestamp: number }> {
  const nowTimestamp = now.getTime();
  const cutoff = nowTimestamp - WINDOW_MS;
  const valid = points
    .map((point) => ({ ...point, timestamp: Date.parse(point.captured_at) }))
    .filter(
      (point) =>
        Number.isFinite(point.timestamp) &&
        point.timestamp >= cutoff &&
        point.timestamp <= nowTimestamp &&
        Number.isInteger(point.star_count) &&
        point.star_count >= 0,
    );
  const actualDates = new Set(
    valid.filter((point) => !point.is_estimated).map((point) => utcDate(point.timestamp)),
  );
  return valid
    .filter((point) => !point.is_estimated || !actualDates.has(utcDate(point.timestamp)))
    .sort((left, right) => left.timestamp - right.timestamp);
}

function plotPoints(points: StarHistoryPoint[], now: Date): PlottedPoint[] {
  const recent = recentHistoryPoints(points, now);
  if (recent.length === 0) {
    return [];
  }
  const cutoff = now.getTime() - WINDOW_MS;
  const counts = recent.map((point) => point.star_count);
  const minimum = Math.min(...counts);
  const maximum = Math.max(...counts);
  const range = Math.max(maximum - minimum, 1);
  return recent.map((point) => ({
    ...point,
    x: PLOT.left + ((point.timestamp - cutoff) / WINDOW_MS) * (PLOT.right - PLOT.left),
    y: PLOT.bottom - ((point.star_count - minimum) / range) * (PLOT.bottom - PLOT.top),
  }));
}

export function StarHistoryGraph({
  points,
  now,
}: {
  points: StarHistoryPoint[];
  now: Date;
}) {
  const plotted = plotPoints(points, now);
  if (plotted.length === 0) {
    return (
      <section className="history-empty" aria-live="polite">
        <span className="status-mark" aria-hidden="true">
          0
        </span>
        <h2>No recent star history yet</h2>
        <p>Tracking is active, but there are no valid measurements in the last 30 days.</p>
      </section>
    );
  }

  const counts = plotted.map((point) => point.star_count);
  const minimum = Math.min(...counts);
  const maximum = Math.max(...counts);
  const estimatedCount = plotted.filter((point) => point.is_estimated).length;
  const actualCount = plotted.length - estimatedCount;
  const cutoff = new Date(now.getTime() - WINDOW_MS);
  const midpoint = new Date(now.getTime() - WINDOW_MS / 2);
  const summary = `${plotted.length} points over the last 30 days: ${actualCount} actual and ${estimatedCount} estimated. Star count ranges from ${starFormatter.format(minimum)} to ${starFormatter.format(maximum)}.`;

  return (
    <figure className="history-figure" aria-labelledby="history-title history-summary">
      <div className="history-heading">
        <div>
          <p className="section-kicker">30-day signal</p>
          <h2 id="history-title">Star history</h2>
        </div>
        <div className="chart-legend" aria-label="Chart legend">
          <span><i className="legend-line actual" aria-hidden="true" />Actual snapshot</span>
          <span><i className="legend-line estimated" aria-hidden="true" />Estimated history</span>
        </div>
      </div>

      <div className="chart-scroll">
        <svg
          className="star-chart"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-labelledby="chart-title chart-description"
        >
          <title id="chart-title">Repository star count over the last 30 days</title>
          <desc id="chart-description">{summary}</desc>
          {[PLOT.top, (PLOT.top + PLOT.bottom) / 2, PLOT.bottom].map((y) => (
            <line key={y} className="chart-grid" x1={PLOT.left} x2={PLOT.right} y1={y} y2={y} />
          ))}
          <text className="chart-axis-label" x={PLOT.left - 8} y={PLOT.top + 4} textAnchor="end">
            {starFormatter.format(maximum)}
          </text>
          <text className="chart-axis-label" x={PLOT.left - 8} y={PLOT.bottom + 4} textAnchor="end">
            {starFormatter.format(minimum)}
          </text>
          {[
            [PLOT.left, cutoff],
            [(PLOT.left + PLOT.right) / 2, midpoint],
            [PLOT.right, now],
          ].map(([x, date]) => (
            <text
              key={(date as Date).toISOString()}
              className="chart-axis-label"
              x={x as number}
              y={HEIGHT - 18}
              textAnchor={x === PLOT.left ? "start" : x === PLOT.right ? "end" : "middle"}
            >
              {dateFormatter.format(date as Date)}
            </text>
          ))}
          {plotted.slice(1).map((point, index) => {
            const previous = plotted[index];
            const estimated = previous.is_estimated || point.is_estimated;
            return (
              <line
                key={`${previous.captured_at}-${point.captured_at}`}
                className={`chart-segment ${estimated ? "estimated" : "actual"}`}
                x1={previous.x}
                y1={previous.y}
                x2={point.x}
                y2={point.y}
              />
            );
          })}
          {plotted.map((point) => (
            <circle
              key={`${point.captured_at}-${point.is_estimated}`}
              className={`chart-point ${point.is_estimated ? "estimated" : "actual"}`}
              cx={point.x}
              cy={point.y}
              r="4.5"
            >
              <title>{`${accessibleDateFormatter.format(new Date(point.timestamp))}: ${starFormatter.format(point.star_count)} stars, ${point.is_estimated ? "estimated" : "actual snapshot"}`}</title>
            </circle>
          ))}
        </svg>
      </div>

      <figcaption id="history-summary">
        <span>{summary}</span>
        <span>Estimates are reconstructed from GitHub star creation history and may not reflect unstars or exact UTC day boundaries.</span>
      </figcaption>
      <div className="visually-hidden">
        <table>
          <caption>Accessible star history data</caption>
          <thead><tr><th>Date</th><th>Stars</th><th>Source</th></tr></thead>
          <tbody>
            {plotted.map((point) => (
              <tr key={`${point.captured_at}-row`}>
                <td>{accessibleDateFormatter.format(new Date(point.timestamp))}</td>
                <td>{point.star_count}</td>
                <td>{point.is_estimated ? "Estimated history" : "Actual snapshot"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
