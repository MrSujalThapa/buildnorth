import type { CollectionView } from "../../api/client";
import CollectionChart from "./CollectionChart";

type Props = {
  collection: CollectionView;
  onOpen: () => void;
  selectMode?: boolean;
  selected?: boolean;
};

export default function CollectionCard({ collection, onOpen, selectMode = false, selected = false }: Props) {
  const odds = collection.portfolio_odds;
  const change = collection.change_pp;
  const hasHistory = collection.series.some((item) => item.points.length);
  const hasTrajectory = collection.series.some((item) => item.points.length > 1);
  return (
    <div className={`market-card collection-card${selectMode ? " is-selectable" : ""}${selected ? " is-selected" : ""}`} role="button" tabIndex={0} aria-pressed={selectMode ? selected : undefined} onClick={onOpen} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpen(); } }} aria-label={selectMode ? `Select ${collection.collection.name} collection` : `Open ${collection.collection.name} collection`}>
      {selectMode ? <span className="selection-indicator" aria-hidden="true">{selected ? "✓" : ""}</span> : null}
      <div className="market-card-header">
        <div className="market-card-title-block">
          <h2>{collection.collection.name}</h2>
        </div>
        <div className="market-card-odds">{odds == null ? "—" : `${odds.toFixed(0)}%`}</div>
      </div>
      <div className={`market-card-return${change == null ? " is-caption" : change >= 0 ? " positive" : " negative"}`}>
        {change == null
          ? `Average of ${collection.priced_goals} of ${collection.total_goals} priced markets`
          : `${change >= 0 ? "+" : ""}${change.toFixed(1)} pp today`}
      </div>
      <div className={`market-card-chart${hasHistory ? hasTrajectory ? "" : " is-sparse" : " is-empty"}`}>
        {hasHistory ? (
          <CollectionChart series={collection.series} interactive={false} />
        ) : (
          <div className="collection-chart-empty" aria-label="No published odds to chart" />
        )}
      </div>
    </div>
  );
}
