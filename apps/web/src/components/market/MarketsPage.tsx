import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, Plus } from "lucide-react";
import type { CollectionView } from "../../api/client";
import type { Market } from "../../adapters/templateTypes";
import CollectionCard from "./CollectionCard";
import MarketCard from "./MarketCard";
import "./markets.css";

type Props = {
  markets: Market[];
  collections: CollectionView[];
  onSelectMarket: (marketId: string) => void;
  onOpenCollection: (collectionId: string) => void;
  onCreateCollection: (name: string) => Promise<void>;
  onArchiveGoals: (goalIds: string[]) => Promise<void>;
  onMoveToCollection: (collectionId: string, goalIds: string[]) => Promise<void>;
};

export default function MarketsPage({
  markets,
  collections,
  onSelectMarket,
  onOpenCollection,
  onCreateCollection,
  onArchiveGoals,
  onMoveToCollection,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [collectionName, setCollectionName] = useState("");
  const [creatingCollection, setCreatingCollection] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    const close = () => setMenuOpen(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menuOpen]);

  function toggleSelected(id: string) {
    setSelected((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  function exitSelect() {
    setSelectMode(false);
    setSelected([]);
    setConfirmDelete(false);
  }

  return (
    <main className="markets-page">
      <section className="markets-shell">
        <header className="markets-header">
          <div>
            <div className="markets-eyebrow">MARKETS</div>
            <h1>Your outcomes</h1>
            <p>Track how new evidence changes the odds of the things you care about.</p>
          </div>
          <div className="markets-toolbar">
            <button
              type="button"
              className={`markets-select${selectMode ? " is-active" : ""}`}
              onClick={() => (selectMode ? exitSelect() : setSelectMode(true))}
            >
              {selectMode ? "Cancel" : "Select"}
            </button>
            <div className="create-split">
              <Link className="create-split-main" to="/new" aria-label="New goal">
                <Plus size={16} strokeWidth={2.2} />
              </Link>
              <button
                type="button"
                className="create-split-caret"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-label="Create"
                onClick={(event) => {
                  event.stopPropagation();
                  setMenuOpen((open) => !open);
                }}
              >
                <ChevronDown size={14} />
              </button>
              {menuOpen ? (
                <div className="create-menu" role="menu">
                  <Link role="menuitem" to="/new" onClick={() => setMenuOpen(false)}>
                    New goal
                  </Link>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      setCreatingCollection(true);
                    }}
                  >
                    New collection
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </header>

        {selectMode ? (
          <div className="markets-actionbar" role="toolbar" aria-label="Goal selection">
            <span>{selected.length} selected</span>
            <label>
              Move to
              <select
                value=""
                onChange={(event) => {
                  const value = event.target.value;
                  if (value && selected.length) void onMoveToCollection(value, selected).then(exitSelect);
                }}
              >
                <option value="">Choose collection</option>
                {collections.map((item) => (
                  <option key={item.collection.collection_id} value={item.collection.collection_id}>
                    {item.collection.name}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="danger" disabled={!selected.length} onClick={() => setConfirmDelete(true)}>
              Delete
            </button>
          </div>
        ) : null}

        {creatingCollection ? (
          <form
            className="collection-create"
            onSubmit={(event) => {
              event.preventDefault();
              if (!collectionName.trim()) return;
              void onCreateCollection(collectionName.trim()).then(() => {
                setCollectionName("");
                setCreatingCollection(false);
              });
            }}
          >
            <label htmlFor="collection-name">Collection name</label>
            <input
              id="collection-name"
              value={collectionName}
              onChange={(event) => setCollectionName(event.target.value)}
              placeholder="Career, Fitness, School…"
              autoFocus
            />
            <div className="composer-actions">
              <button type="submit" disabled={!collectionName.trim()}>Create collection</button>
              <button type="button" className="secondary" onClick={() => setCreatingCollection(false)}>
                Cancel
              </button>
            </div>
          </form>
        ) : null}

        {collections.length ? (
          <div className="markets-grid collections-grid">
            {collections.map((collection) => (
              <CollectionCard
                key={collection.collection.collection_id}
                collection={collection}
                onOpen={() => onOpenCollection(collection.collection.collection_id)}
              />
            ))}
          </div>
        ) : null}

        <div className="markets-grid">
          {markets.length === 0 && collections.length === 0 ? (
            <div className="unpriced-state markets-empty" role="status">
              <strong>No goals yet</strong>
              <span>Create a goal to start tracking outcome odds.</span>
            </div>
          ) : (
            markets.map((market) => (
              <MarketCard
                key={market.id}
                market={market}
                selectMode={selectMode}
                selected={selected.includes(market.id)}
                onClick={() => (selectMode ? toggleSelected(market.id) : onSelectMarket(market.id))}
              />
            ))
          )}
        </div>
      </section>

      {confirmDelete ? (
        <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="delete-goals-title">
          <div className="confirm-card">
            <h2 id="delete-goals-title">Delete {selected.length} goal{selected.length === 1 ? "" : "s"}?</h2>
            <p>
              Goals are archived, not erased. Forecast history, evidence, and usage accounting stay intact. You can restore a goal later.
            </p>
            <div className="composer-actions">
              <button
                type="button"
                className="danger"
                onClick={() => {
                  void onArchiveGoals(selected).then(exitSelect);
                }}
              >
                Archive goals
              </button>
              <button type="button" className="secondary" onClick={() => setConfirmDelete(false)}>
                Keep
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </main>
  );
}
