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
  onDeleteCollections: (collectionIds: string[]) => Promise<void>;
  onMoveToCollection: (collectionId: string, goalIds: string[]) => Promise<void>;
  onShareMarkets?: (goalIds: string[]) => Promise<void>;
};

export default function MarketsPage({
  markets,
  collections,
  onSelectMarket,
  onOpenCollection,
  onCreateCollection,
  onArchiveGoals,
  onDeleteCollections,
  onMoveToCollection,
  onShareMarkets,
}: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [selectedCollections, setSelectedCollections] = useState<string[]>([]);
  const [moreOpen, setMoreOpen] = useState(false);
  const [collectionName, setCollectionName] = useState("");
  const [creatingCollection, setCreatingCollection] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [selectionError, setSelectionError] = useState(false);

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
    setSelectedCollections([]);
    setMoreOpen(false);
    setConfirmDelete(false);
    setSelectionError(false);
  }

  return (
    <main className="markets-page">
      <section className="markets-shell">
        <header className="markets-header">
          <div>
            <div className="markets-eyebrow">MARKETS</div>
            <h1>Your outcomes</h1>
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

        <div className="markets-grid">
          {markets.length === 0 && collections.length === 0 ? (
            <div className="unpriced-state markets-empty" role="status">
              <strong>No goals yet</strong>
              <span>Create a goal to start tracking outcome odds.</span>
            </div>
          ) : (
            <>
            {collections.map((collection) => (
              <CollectionCard
                key={collection.collection.collection_id}
                collection={collection}
                selectMode={selectMode}
                selected={selectedCollections.includes(collection.collection.collection_id)}
                onOpen={() => selectMode ? setSelectedCollections((current) => current.includes(collection.collection.collection_id) ? current.filter((id) => id !== collection.collection.collection_id) : [...current, collection.collection.collection_id]) : onOpenCollection(collection.collection.collection_id)}
              />
            ))}
            {markets.map((market) => (
              <MarketCard
                key={market.id}
                market={market}
                selectMode={selectMode}
                selected={selected.includes(market.id)}
                onClick={() => (selectMode ? toggleSelected(market.id) : onSelectMarket(market.id))}
              />
            ))}
            </>
          )}
        </div>
      </section>

      {selectMode ? (
        <div className="markets-actionbar" role="toolbar" aria-label="Selection actions">
          <strong>{selected.length + selectedCollections.length} selected</strong>
          <button type="button" className="danger" disabled={!selected.length && !selectedCollections.length} onClick={() => setConfirmDelete(true)}>Delete / Archive</button>
          <button
            type="button"
            disabled={!selected.length || !onShareMarkets}
            onClick={() => { if (onShareMarkets) void onShareMarkets(selected); }}
          >
            Share
          </button>
          <div className="selection-more">
            <button type="button" aria-label="More selection actions" aria-expanded={moreOpen} onClick={() => setMoreOpen((open) => !open)}>···</button>
            {moreOpen ? <div className="selection-more-menu" role="menu">
              <button type="button" role="menuitem" onClick={() => { setSelected(markets.map((market) => market.id)); setSelectedCollections(collections.map((item) => item.collection.collection_id)); setMoreOpen(false); }}>Select all</button>
              {selected.length ? collections.map((item) => <button key={item.collection.collection_id} type="button" role="menuitem" onClick={() => { void onMoveToCollection(item.collection.collection_id, selected).then(exitSelect); }}>Move to {item.collection.name}</button>) : null}
            </div> : null}
          </div>
        </div>
      ) : null}

      {confirmDelete ? (
        <div className="confirm-layer" role="dialog" aria-modal="true" aria-labelledby="delete-goals-title">
          <div className="confirm-card">
            <h2 id="delete-goals-title">Remove selected items?</h2>
            <p>
              Goals will be archived. Collections will be deleted, while their goals and history stay.
            </p>
            {selectionError ? <p role="alert">Could not remove every selected item. Please try again.</p> : null}
            <div className="composer-actions">
              <button
                type="button"
                className="danger"
                onClick={() => {
                  setSelectionError(false);
                  void Promise.all([
                    selected.length ? onArchiveGoals(selected) : Promise.resolve(),
                    selectedCollections.length ? onDeleteCollections(selectedCollections) : Promise.resolve(),
                  ]).then(exitSelect).catch(() => setSelectionError(true));
                }}
              >
                Confirm
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
