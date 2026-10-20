import type { CollectionView } from "../../api/client";
import CollectionChart from "./CollectionChart";

type Props = {
  collection: CollectionView;
  onOpen: () => void;
};

function progressLabel(collection: CollectionView) {
  const value = collection.progress.value;
  if (value == null) return "Progress unavailable";
  return `${Math.round(value * 100)}% progress`;
}

export default function CollectionCard({ collection, onOpen }: Props) {
  return (
    <button type="button" className="market-card collection-card" onClick={onOpen}>
      <div className="market-card-header">
        <div className="market-card-title-block">
          <div className="market-card-category">Collection</div>
          <h2>{collection.collection.name}</h2>
        </div>
        <div className="market-card-odds">{progressLabel(collection)}</div>
      </div>
      <div className="market-card-return">
        {collection.progress.available}/{collection.progress.total} goals measured · not a joint probability
      </div>
      <div className="market-card-chart">
        {collection.series.some((item) => item.points.length) ? (
          <CollectionChart series={collection.series} interactive={false} />
        ) : (
          <div className="unpriced-state">
            <strong>{collection.progress.total ? "No measured progress yet" : "Empty collection"}</strong>
            <span>{collection.progress.total ? "Add measurable evidence to a goal." : "Add a goal to see its progress here."}</span>
          </div>
        )}
      </div>
    </button>
  );
}
