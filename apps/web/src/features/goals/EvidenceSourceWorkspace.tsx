import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Blocks, Check, ExternalLink } from "lucide-react";
import {
  api,
  type PluginView,
  type SourcePlannerProposal,
  type SourceRecipeRecord,
  type SourceWatchRecord,
  type WorkflowSnapshot,
} from "../../api/client";
import { PluginBrandIcon } from "../../components/plugins/PluginBrandIcon";
import { isPluginConnected, pluginViewToDisplay } from "../../components/plugins/pluginPresentation";
import { AgentProgress } from "../agents/AgentProgress";
import { EvidenceWorkflow } from "./EvidenceWorkflow";
import { additionalRequiredArguments, schemaBody } from "./readArguments";
import { ResourceMark, SourcePreviewView, sourceNoun } from "./SourcePreview";
import "./evidence.css";

type Props = {
  goalId: string;
  goalTitle: string;
  forecastLabel?: string;
  onBack?: () => void;
  initialSnapshot?: WorkflowSnapshot | null;
  onSnapshotChange?: (snapshot: WorkflowSnapshot | null) => void;
};

type SourceBucket = "recommended" | "connected" | "other";
const monitoringEnabled = import.meta.env.VITE_BACKGROUND_MONITORING === "true";

export function watchedResourceIds(recipe: SourceRecipeRecord): string[] {
  const prefix = `composio://${recipe.plugin_id}/`;
  const uris = [...new Set(recipe.steps.map((step) => step.resource_uri).filter((uri) => uri?.startsWith(prefix)))];
  return uris.map((uri) => uri!.slice(prefix.length));
}

export function watchScope(pluginId: string, includeDescendants: boolean): "resource" | "parent" {
  return pluginId === "notion" && includeDescendants ? "parent" : "resource";
}

type SourceCardModel = {
  pluginId: string;
  name: string;
  description: string;
  logoUrl?: string;
  bucket: SourceBucket;
  relevance: string;
  rationale: string;
  connected: boolean;
  lastSyncLabel?: string;
  contributes: string[];
  enabled: boolean;
  resources: SourcePlannerProposal["recommended"][number]["resources"];
};

function formatProbability(value: number | null | undefined): string | undefined {
  if (value == null || Number.isNaN(value)) return undefined;
  return `${(value * 100).toFixed(1)}%`;
}

function buildSourceCards(plan: SourcePlannerProposal | undefined, plugins: PluginView[], savedIds: Set<string>): SourceCardModel[] {
  const displayById = new Map(plugins.map((plugin) => [plugin.definition.id, pluginViewToDisplay(plugin)]));
  const pluginById = new Map(plugins.map((plugin) => [plugin.definition.id, plugin]));
  const recommendedIds = new Set((plan?.recommended ?? []).map((item) => item.plugin_id));
  const irrelevantIds = new Set((plan?.irrelevant ?? []).map((item) => item.plugin_id));
  const cards: SourceCardModel[] = [];

  for (const source of plan?.recommended ?? []) {
    const plugin = pluginById.get(source.plugin_id);
    const display = displayById.get(source.plugin_id);
    cards.push({
      pluginId: source.plugin_id,
      name: display?.name ?? source.plugin_id,
      description: display?.description ?? source.rationale,
      logoUrl: plugin?.definition.logo_url ?? undefined,
      bucket: "recommended",
      relevance: source.relevance,
      rationale: source.rationale,
      connected: plugin ? isPluginConnected(plugin) : false,
      lastSyncLabel: display?.lastSyncLabel,
      contributes: display?.reads ?? [],
      enabled: true,
      resources: source.resources,
    });
  }

  for (const plugin of plugins) {
    const id = plugin.definition.id;
    if (id === "manual" || id === "csv" || recommendedIds.has(id)) continue;
    const display = displayById.get(id)!;
    const connected = isPluginConnected(plugin);
    if (!connected && irrelevantIds.has(id) && !savedIds.has(id)) continue;
    cards.push({
      pluginId: id,
      name: display.name,
      description: display.description,
      logoUrl: plugin.definition.logo_url ?? undefined,
      bucket: connected || savedIds.has(id) ? "connected" : "other",
      relevance: irrelevantIds.has(id) ? "low relevance" : connected ? "available" : "not connected",
      rationale:
        plan?.irrelevant.find((item) => item.plugin_id === id)?.rationale ??
        (connected ? "Connected" : "Connect to use"),
      connected,
      lastSyncLabel: display.lastSyncLabel,
      contributes: display.reads,
      enabled: false,
      resources: plan?.irrelevant.find((item) => item.plugin_id === id)?.resources ?? [],
    });
  }

  return cards;
}

export function EvidenceSourceWorkspace({
  goalId,
  goalTitle,
  forecastLabel,
  onBack,
  initialSnapshot = null,
  onSnapshotChange,
}: Props) {
  const queryClient = useQueryClient();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [planRequested, setPlanRequested] = useState(false);
  const [selectedResources, setSelectedResources] = useState<Record<string, string[]>>({});
  const [resourceRefs, setResourceRefs] = useState<Record<string, string>>({});
  const [activityTypes, setActivityTypes] = useState<Record<string, string[]>>({});
  const [readArguments, setReadArguments] = useState<Record<string, Record<string, string>>>({});
  const [snapshot, setSnapshot] = useState<WorkflowSnapshot | null>(initialSnapshot);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const plugins = useQuery({
    queryKey: ["plugins-connected"],
    queryFn: ({ signal }) => api.connectedPlugins(signal),
    staleTime: 30_000,
  });
  const sourcePlan = useQuery({
    queryKey: ["evidence-source-plan", goalId],
    queryFn: ({ signal }) => api.evidenceSourcePlan(goalId, signal),
    enabled: Boolean(goalId) && planRequested,
    retry: false,
  });
  const recipes = useQuery({
    queryKey: ["evidence-source-recipes", goalId],
    queryFn: ({ signal }) => api.evidenceSourceRecipes(goalId, signal),
    enabled: Boolean(goalId),
  });
  const watches = useQuery({
    queryKey: ["evidence-source-watches", goalId],
    queryFn: ({ signal }) => api.sourceWatches(goalId, signal),
    enabled: Boolean(goalId) && monitoringEnabled,
  });
  const updateWatches = useMutation({
    mutationFn: ({ recipe, resourceIds = [], selected = [], status, scope = "resource" }: {
      recipe: SourceRecipeRecord;
      resourceIds?: string[];
      selected?: SourceWatchRecord[];
      status: "active" | "paused" | "revoked";
      scope?: "resource" | "parent";
    }) => Promise.all([
      ...resourceIds.map((resourceId) => api.saveSourceWatch(goalId, {
        plugin_id: recipe.plugin_id, resource_id: resourceId,
        scope: watchScope(recipe.plugin_id, scope === "parent"),
      })),
      ...selected.map((watch) => api.updateSourceWatch(goalId, watch.id, status)),
    ]),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["evidence-source-watches", goalId] }); },
  });
  const syncJob = useQuery({
    queryKey: ["evidence-source-sync", goalId],
    queryFn: ({ signal }) => api.latestEvidenceSourceSync(goalId, signal),
    enabled: Boolean(goalId),
    refetchInterval: (query) => ["queued", "fetching_sources", "processing_evidence", "updating_forecast"].includes(query.state.data?.status ?? "") ? 2000 : false,
  });
  const syncActive = ["queued", "fetching_sources", "processing_evidence", "updating_forecast"].includes(syncJob.data?.status ?? "");
  useEffect(() => {
    if (syncJob.data?.status !== "completed") return;
    void queryClient.invalidateQueries({ queryKey: ["evidence", goalId] });
    void queryClient.invalidateQueries({ queryKey: ["goal", goalId] });
    void queryClient.invalidateQueries({ queryKey: ["market-history", goalId] });
    void queryClient.invalidateQueries({ queryKey: ["goals", "dashboard"] });
    void queryClient.invalidateQueries({ queryKey: ["what-if-baseline", goalId] });
  }, [goalId, queryClient, syncJob.data?.id, syncJob.data?.status]);
  const cards = useMemo(
    () => buildSourceCards(sourcePlan.data, plugins.data ?? [], new Set((recipes.data ?? []).map((recipe) => recipe.plugin_id))),
    [plugins.data, sourcePlan.data, recipes.data],
  );

  const saveRecipe = useMutation({
    mutationFn: (body: {
      pluginId: string;
      label: string;
      resourceIds: string[];
      activityTypes?: string[];
      readArguments?: Record<string, string>;
    }) =>
      api.saveEvidenceSourceRecipe(goalId, body.pluginId, {
        label: body.label,
        resource_ids: body.resourceIds,
        approved: true,
        activity_types: body.activityTypes,
        read_arguments: body.readArguments,
      }),
    onSuccess: () => {
      setSyncMessage("Source saved");
      void queryClient.invalidateQueries({ queryKey: ["evidence-source-recipes", goalId] });
    },
  });

  const syncSources = useMutation({
    mutationFn: () => { setSyncMessage(null); return api.syncEvidenceSources(goalId); },
    onSuccess: (data) => { queryClient.setQueryData(["evidence-source-sync", goalId], data); },
  });

  const toggleActivity = (pluginId: string, activity: string) => {
    setActivityTypes((current) => {
      if (pluginId !== "github") return { ...current, [pluginId]: [activity] };
      const existing = new Set(current[pluginId] ?? []);
      if (existing.has(activity)) existing.delete(activity);
      else existing.add(activity);
      return { ...current, [pluginId]: [...existing] };
    });
  };

  const buildResourceIds = (pluginId: string) => {
    if (pluginId === "github") {
      const repository = selectedResources.github?.[0] ?? "";
      const branch = (resourceRefs.github ?? "").trim();
      return repository ? [`${repository}${branch ? `@${branch}` : ""}`] : [];
    }
    const base = selectedResources[pluginId] ?? [];
    if (pluginId === "notion") return base;
    return (resourceRefs[pluginId] ?? "").trim() ? [(resourceRefs[pluginId] ?? "").trim()] : base;
  };

  const toggleResource = (pluginId: string, resourceId: string) => {
    setSelectedResources((current) => {
      if (pluginId !== "notion" && pluginId !== "calendar") return { ...current, [pluginId]: [resourceId] };
      const existing = new Set(current[pluginId] ?? []);
      if (existing.has(resourceId)) existing.delete(resourceId);
      else existing.add(resourceId);
      return { ...current, [pluginId]: [...existing] };
    });
  };

  const savedRecipes = recipes.data ?? [];
  const sections: { key: SourceBucket; title: string }[] = [
    { key: "recommended", title: "Recommended sources" },
    { key: "connected", title: "Connected sources" },
  ];

  return (
    <main className="evidence-page">
      <div className="evidence-shell">
        <header className="evidence-header">
          <div className="evidence-header-top">
            {onBack ? (
              <button type="button" className="evidence-back" onClick={onBack}>
                ← Back to market
              </button>
            ) : null}
          </div>
          <h1>Evidence</h1>
          <div className="evidence-context">
            <span>
              Goal: <strong>{goalTitle}</strong>
            </span>
            {forecastLabel ? (
              <span>
                Current forecast: <strong>{forecastLabel}</strong>
              </span>
            ) : null}
          </div>
        </header>

        {plugins.isLoading ? <p role="status">Loading connected sources…</p> : null}
        <div className="evidence-source-tools">
          <button type="button" onClick={() => { if (planRequested) void sourcePlan.refetch(); else setPlanRequested(true); }} disabled={sourcePlan.isFetching}>
            {sourcePlan.isFetching ? "Finding sources…" : "Find relevant sources"}
          </button>
          <Link to="/plugins">Browse integrations</Link>
        </div>
        {sourcePlan.isError ? (
          <p className="field-hint" role="alert">Suggestions are unavailable. Connected sources still work.</p>
        ) : null}
        {planRequested && sourcePlan.isSuccess && !sourcePlan.data.recommended.length ? (
          <p className="field-hint" role="status">No suggested sources yet. Choose an authorized source below.</p>
        ) : null}

        {sections.map((section) => {
          const sectionCards = cards.filter((card) => card.bucket === section.key);
          if (!sectionCards.length) return null;
          return (
            <section key={section.key} className="evidence-section" aria-labelledby={`${section.key}-sources`}>
              <div className="evidence-section-heading">
                <h2 id={`${section.key}-sources`}>{section.title}</h2>
                <span>{sectionCards.length}</span>
              </div>
              <div className="evidence-source-grid">
                {sectionCards.map((card) => {
                  const expanded = expandedId === card.pluginId;
                  return (
                    <div key={card.pluginId}>
                      <button
                        type="button"
                        className="evidence-source-card"
                        aria-expanded={expanded}
                        onClick={() => setExpandedId(expanded ? null : card.pluginId)}
                      >
                        <span className="plugin-icon">
                          <PluginBrandIcon
                            id={card.pluginId}
                            logoUrl={card.logoUrl}
                            Icon={pluginViewToDisplay({
                              definition: {
                                id: card.pluginId,
                                name: card.name,
                                description: card.description,
                                category: "integration",
                                provider_type: "composio",
                                logo_url: card.logoUrl ?? null,
                                capabilities: [],
                                used_for: card.contributes,
                              },
                              connection: {
                                plugin_id: card.pluginId,
                                status: card.connected ? "connected" : "not_connected",
                                connected_at: null,
                                last_sync_at: null,
                                permissions: [],
                                account_metadata: {},
                                error: null,
                              },
                            }).Icon}
                          />
                        </span>
                        <span>
                          <strong>{card.name}</strong>
                          {card.rationale && card.rationale !== "Connected" ? <small>{card.rationale}</small> : null}
                          <span className="evidence-source-meta">
                            {section.key === "recommended" ? <span className="evidence-pill recommended">Suggested</span> : null}
                            <span className={`evidence-pill ${card.connected ? "connected" : ""}`}>
                              {card.connected ? "Connected" : "Not connected"}
                            </span>
                          </span>
                        </span>
                      </button>
                      {expanded ? (
                        <SourceResourcePanel
                          source={card}
                          selectedResources={selectedResources[card.pluginId] ?? []}
                          resourceRef={resourceRefs[card.pluginId] ?? ""}
                          selectedActivities={activityTypes[card.pluginId] ?? []}
                          readArguments={readArguments[card.pluginId] ?? {}}
                          onResourceRefChange={(value) =>
                            setResourceRefs((current) => ({ ...current, [card.pluginId]: value }))
                          }
                          onToggleActivity={(activity) => toggleActivity(card.pluginId, activity)}
                          onArgumentChange={(key, value) => setReadArguments((current) => ({
                            ...current,
                            [card.pluginId]: { ...current[card.pluginId], [key]: value },
                          }))}
                          onToggleResource={(resourceId) => toggleResource(card.pluginId, resourceId)}
                          onApprove={(label, argumentsForRead) =>
                            saveRecipe.mutate({
                              pluginId: card.pluginId,
                              label: label || card.name,
                              resourceIds: buildResourceIds(card.pluginId),
                              activityTypes: activityTypes[card.pluginId],
                              readArguments: argumentsForRead,
                            })
                          }
                          approvePending={saveRecipe.isPending}
                        />
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}

        {savedRecipes.length ? (
          <div className="evidence-sync-bar">
            <div>
              <strong>{savedRecipes.length} saved source{savedRecipes.length === 1 ? "" : "s"}</strong>
              <ul className="evidence-recipe-list" aria-label="Saved sources">
                {savedRecipes.map((recipe: SourceRecipeRecord) => (
                  <li key={`${recipe.plugin_id}-${recipe.label}`} className={monitoringEnabled ? "watchable" : undefined}>
                    <span>{recipe.label}{plugins.data?.some((plugin) => plugin.definition.id === recipe.plugin_id && !isPluginConnected(plugin)) ? " · Reconnect source" : ""}</span>
                    {monitoringEnabled && watchedResourceIds(recipe).length ? (() => {
                      const resourceIds = watchedResourceIds(recipe);
                      const selected = resourceIds.map((resourceId) => watches.data?.filter((item) => item.plugin_id === recipe.plugin_id && item.resource_id === resourceId)
                        .sort((a, b) => ({ active: 0, paused: 1, revoked: 2 })[a.status] - ({ active: 0, paused: 1, revoked: 2 })[b.status])[0]);
                      const active = selected.filter((watch) => watch?.status === "active") as SourceWatchRecord[];
                      const paused = selected.filter((watch) => watch?.status === "paused") as SourceWatchRecord[];
                      const revoked = selected.filter((watch) => watch?.status === "revoked") as SourceWatchRecord[];
                      const existing = selected.filter((watch): watch is SourceWatchRecord => Boolean(watch));
                      const disconnected = plugins.data?.some((plugin) => plugin.definition.id === recipe.plugin_id && !isPluginConnected(plugin));
                      return <span className="evidence-watch-actions">
                        {active.some((watch) => watch.last_error) ? <span role="status" className="evidence-watch-error">Monitoring needs attention</span> : null}
                        {active.length ? <span className="evidence-watch-state">Monitoring {active.length} of {resourceIds.length}{active.some((watch) => watch.scope === "parent") ? " · accessible subpages included" : ""}</span> : null}
                        <button type="button" disabled={Boolean(disconnected) || updateWatches.isPending} onClick={() => {
                          if (active.length === resourceIds.length) updateWatches.mutate({ recipe, selected: active, status: "paused" });
                          else {
                            const missing = resourceIds.filter((resourceId) => !selected.some((watch) => watch?.resource_id === resourceId && watch.status !== "revoked"));
                            updateWatches.mutate({ recipe, resourceIds: missing, selected: paused, status: "active" });
                          }
                        }}>{active.length === resourceIds.length ? "Pause" : paused.length === resourceIds.length ? "Resume" : revoked.length === resourceIds.length ? "Restart" : `Monitor ${resourceIds.length === 1 ? "source" : `${resourceIds.length} sources`}`}</button>
                        {recipe.plugin_id === "notion" && !active.length && !paused.length ? <button type="button" disabled={Boolean(disconnected) || updateWatches.isPending} onClick={() => updateWatches.mutate({ recipe, resourceIds, status: "active", scope: "parent" })}>Include accessible subpages</button> : null}
                        {existing.some((watch) => watch.status !== "revoked") ? <button type="button" disabled={updateWatches.isPending} onClick={() => updateWatches.mutate({ recipe, selected: existing.filter((watch) => watch.status !== "revoked"), status: "revoked" })}>Stop</button> : null}
                      </span>;
                    })() : null}
                  </li>
                ))}
              </ul>
            </div>
            <button type="button" disabled={syncSources.isPending || syncActive} onClick={() => syncSources.mutate()}>
              {syncActive ? "Syncing…" : "Sync sources"}
            </button>
          </div>
        ) : null}

        {syncMessage ? <p className="field-hint" role="status">{syncMessage}</p> : null}
        {syncJob.data ? <p className="evidence-sync-status" role="status">{
          syncJob.data.status === "queued" ? "Sync queued" :
          syncJob.data.status === "fetching_sources" ? "Fetching sources…" :
          syncJob.data.status === "processing_evidence" ? "Processing evidence…" :
          syncJob.data.status === "updating_forecast" ? "Updating forecast…" :
          syncJob.data.status === "completed" ?
            syncJob.data.receipt.workflow_status === "unchanged"
              ? "Sources checked · no relevant goal change"
              : Number(syncJob.data.receipt.records_added ?? 0) > 0
              ? `Synced · ${Number(syncJob.data.receipt.records_added)} new record${Number(syncJob.data.receipt.records_added) === 1 ? "" : "s"}`
              : "No new updates"
            : syncJob.data.error ?? "Sync failed. Try again."
        }</p> : null}
        {saveRecipe.isError ? <p className="field-hint" role="alert">Could not save source: {String(saveRecipe.error)}</p> : null}
        {updateWatches.isError ? <p className="field-hint" role="alert">Could not update monitoring. Check source access and try again.</p> : null}
        {syncSources.isError ? <p className="field-hint" role="alert">Sync failed: {String(syncSources.error)}</p> : null}

        <AgentProgress snapshot={snapshot} />

        <DatasetUpload goalId={goalId} />

        <section className="evidence-manual-card">
          <h2>Manual evidence</h2>
          <EvidenceWorkflow
            goalId={goalId}
            embedded
            initialSnapshot={initialSnapshot}
            onSnapshotChange={(value) => {
              setSnapshot(value);
              onSnapshotChange?.(value);
            }}
          />
        </section>
      </div>
    </main>
  );
}

function DatasetUpload({ goalId }: { goalId: string }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [valueColumn, setValueColumn] = useState("");
  const [timeColumn, setTimeColumn] = useState("");
  const [metric, setMetric] = useState("");
  const uploads = useQuery({
    queryKey: ["uploads", goalId],
    queryFn: ({ signal }) => api.listUploads(goalId, signal),
  });
  const send = useMutation({
    mutationFn: (file: File) => api.uploadDataset(goalId, file),
    onSuccess: () => {
      setFile(null);
      void queryClient.invalidateQueries({ queryKey: ["uploads", goalId] });
    },
  });
  const chooseFile = (candidate?: File) => {
    if (!candidate) return;
    if (!/\.(csv|xlsx|pdf|txt|md)$/i.test(candidate.name)) {
      setFileError("Choose a CSV, Excel, PDF, or text file.");
      return;
    }
    if (candidate.size > 5_000_000) {
      setFileError("File must be under 5 MB.");
      return;
    }
    setFile(candidate);
    setFileError(null);
  };
  const latest = uploads.data?.at(-1);
  const map = useMutation({
    mutationFn: () => {
      if (!latest) throw new Error("missing upload");
      return api.mapUpload(goalId, latest.upload_id, {
        metric: metric || latest.preview.columns?.[1] || "measurement",
        value_column: valueColumn || latest.preview.columns?.[1] || "",
        observed_at_column: timeColumn || latest.preview.columns?.[0],
        observation_kind: "snapshot",
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["evidence", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["market-history", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["goal", goalId] });
    },
  });
  const columns = latest?.preview.columns ?? [];

  return (
    <section className="evidence-manual-card">
      <h2>Upload a dataset</h2>
      <form
        className="file-upload-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (file) send.mutate(file);
        }}
      >
        <label
          className={`file-drop-label${dragging ? " dragging" : ""}`}
          htmlFor="dataset"
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={(event) => { event.preventDefault(); setDragging(false); }}
          onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0]); }}
        >
          <strong>{file ? file.name : "Drop a file here"}</strong>
          <span>{file ? `${(file.size / 1024).toFixed(0)} KB · Choose another file` : "or choose a CSV, Excel, PDF, or text file · 5 MB max"}</span>
          <input id="dataset" name="dataset" type="file" accept=".csv,.xlsx,.pdf,.txt,.md" onChange={(event) => chooseFile(event.target.files?.[0])} />
        </label>
        <div className="upload-actions">
          {file ? <button type="button" className="quiet-button" onClick={() => { setFile(null); setFileError(null); }}>Remove</button> : null}
          <button type="submit" disabled={send.isPending || !file}>
          {send.isPending ? "Uploading…" : "Upload"}
          </button>
        </div>
        {send.isPending ? <div className="upload-progress" role="progressbar" aria-label="Upload in progress" /> : null}
        {fileError || send.error ? <p className="field-hint" role="alert">{fileError ?? String(send.error)}</p> : null}
        {send.isSuccess ? <p className="field-hint" role="status">Upload complete.</p> : null}
      </form>
      {latest ? (
        <div className="upload-preview">
          <p className="field-hint">
            {latest.filename} · {latest.preview.kind} · {latest.preview.row_count ?? 0} rows
            {latest.preview.note ? ` · ${latest.preview.note}` : ""}
          </p>
          {columns.length ? (
            <form
              className="upload-mapping-form"
              onSubmit={(event) => {
                event.preventDefault();
                map.mutate();
              }}
            >
              <label htmlFor="upload-metric">Metric name</label>
              <input id="upload-metric" value={metric} onChange={(event) => setMetric(event.target.value)} placeholder={columns[1] ?? "subscribers"} />
              <label htmlFor="upload-value">Value column</label>
              <select id="upload-value" value={valueColumn} onChange={(event) => setValueColumn(event.target.value)}>
                <option value="">Select column</option>
                {columns.map((column) => (
                  <option key={column} value={column}>
                    {column}
                  </option>
                ))}
              </select>
              <label htmlFor="upload-time">Date column</label>
              <select id="upload-time" value={timeColumn} onChange={(event) => setTimeColumn(event.target.value)}>
                <option value="">Select column</option>
                {columns.map((column) => (
                  <option key={`time-${column}`} value={column}>
                    {column}
                  </option>
                ))}
              </select>
              <button type="submit" disabled={map.isPending || !(valueColumn || columns[1])}>
                {map.isPending ? "Importing…" : "Import measurements"}
              </button>
              {map.isSuccess ? <p className="field-hint" role="status">Measurements imported.</p> : null}
              {map.isError ? <p className="field-hint" role="alert">{String(map.error)}</p> : null}
            </form>
          ) : (
            <p className="field-hint">This file is stored as research text. It is not used as model instructions.</p>
          )}
        </div>
      ) : null}
    </section>
  );
}

function SourceResourcePanel({
  source,
  selectedResources,
  resourceRef,
  selectedActivities,
  readArguments,
  onResourceRefChange,
  onToggleActivity,
  onArgumentChange,
  onToggleResource,
  onApprove,
  approvePending,
}: {
  source: SourceCardModel;
  selectedResources: string[];
  resourceRef: string;
  selectedActivities: string[];
  readArguments: Record<string, string>;
  onResourceRefChange: (value: string) => void;
  onToggleActivity: (activity: string) => void;
  onArgumentChange: (key: string, value: string) => void;
  onToggleResource: (resourceId: string) => void;
  onApprove: (label: string, readArguments: Record<string, string>) => void;
  approvePending: boolean;
}) {
  const [resourceQuery, setResourceQuery] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(50);
  const resources = useQuery({
    queryKey: ["plugin-resources", source.pluginId],
    queryFn: ({ signal }) => api.pluginResources(source.pluginId, signal),
    staleTime: 60_000,
    enabled: source.connected,
  });
  const capabilities = useQuery({
    queryKey: ["plugin-capabilities", source.pluginId],
    queryFn: ({ signal }) => api.pluginCapabilities(source.pluginId, signal),
    staleTime: 60_000,
    enabled: source.connected,
  });
  const githubActivities = [
    { value: "commits", label: "Commits", tools: ["GITHUB_LIST_COMMITS"] },
    { value: "pull_requests", label: "Pull requests", tools: ["GITHUB_GET_PULL_REQUESTS", "GITHUB_LIST_PULL_REQUESTS"] },
    { value: "issues", label: "Issues", tools: ["GITHUB_LIST_ISSUES_FOR_A_REPOSITORY", "GITHUB_LIST_REPOSITORY_ISSUES"] },
  ];
  const activityOptions = source.pluginId === "github"
    ? githubActivities.filter((activity) => (capabilities.data ?? []).some((item) => activity.tools.includes(item.tool_name ?? "")))
    : ["notion", "calendar"].includes(source.pluginId) ? []
    : (capabilities.data ?? []).filter((item) => {
      const properties = item.input_schema?.parameters?.properties ?? item.input_schema?.properties ?? {};
      return item.tool_name && (item.operation === "read" || item.operation.endsWith(".read"))
        && Object.keys(properties).some((key) => /(^|_)(id|query|channel|q)$|calendarId|spreadsheetId/.test(key));
    }).map((item) => ({ value: item.tool_name!, label: item.label, tools: [item.tool_name!] }));
  const generic = !["github", "notion", "calendar"].includes(source.pluginId);
  const selectedCapability = (capabilities.data ?? []).find((item) => item.tool_name === selectedActivities[0]);
  const selectedSchema = schemaBody(selectedCapability?.input_schema);
  const requiredFields = generic ? additionalRequiredArguments(selectedSchema) : [];
  const schemaProperties = selectedSchema.properties ?? {};
  const requiredArgumentsReady = requiredFields.every((key) => (readArguments[key] ?? "").trim());
  const options = (resources.data ?? [])
          .map((item) => {
            const resourceId = item.uri.replace(/^composio:\/\/[^/]+\//, "") || item.name;
            const planned = source.resources.find((row) => row.resource_id === resourceId || row.label === item.name);
            return {
              resource_id: resourceId,
              label: item.name,
              rationale:
                planned?.why ||
                planned?.rationale ||
                item.description ||
                "Discovered from connected provider.",
              resource_type: planned?.resource_type || item.resource_type || "resource",
              goal_relevance: planned?.goal_relevance,
              state_variables: planned?.state_variables ?? [],
              recommended: planned?.recommended ?? false,
              url: item.metadata?.url,
            };
          })
          .sort((left, right) => Number(right.recommended) - Number(left.recommended));
  const visibleOptions = options.filter((item) => item.label.toLowerCase().includes(resourceQuery.toLowerCase()));
  const selectedOption = options.find((item) => selectedResources.includes(item.resource_id));
  const noun = sourceNoun(options.map((item) => item.resource_type));
  const [measurementId, setMeasurementId] = useState<string | null>(null);
  const [trackingLabel, setTrackingLabel] = useState("");
  const [previewArguments, setPreviewArguments] = useState<Record<string, string>>({});
  const preview = useQuery({
    queryKey: ["plugin-preview", source.pluginId, selectedOption?.resource_id, previewArguments],
    queryFn: () => api.previewPluginSource(source.pluginId, {
      resource_id: selectedOption?.resource_id ?? "",
      resource_title: selectedOption?.label,
      resource_type: selectedOption?.resource_type,
      arguments: previewArguments,
    }),
    enabled: Boolean(selectedOption),
    staleTime: 60_000,
  });
  useEffect(() => {
    setMeasurementId(null);
    setTrackingLabel("");
    setPreviewArguments({});
  }, [selectedOption?.resource_id]);
  useEffect(() => {
    const data = preview.data;
    if (!data?.tool_name || !generic) return;
    if (selectedActivities[0] !== data.tool_name) onToggleActivity(data.tool_name);
    for (const [key, value] of Object.entries(data.arguments)) {
      const identifiesResource = /(^|_)(id|query|channel|q)$|calendarId|spreadsheetId/.test(key);
      if (!identifiesResource && !(readArguments[key] ?? "").trim() && value) onArgumentChange(key, value);
    }
    const measurement = data.measurements[0];
    if (measurement) {
      setMeasurementId((current) => current ?? measurement.id);
      setTrackingLabel((current) => current || measurement.label);
    }
  }, [preview.data, generic, onArgumentChange, onToggleActivity, readArguments, selectedActivities]);

  return (
    <div className="evidence-resource-panel">
      <div className="source-connect-row">
        <span className="source-connect-mark" aria-hidden="true">
          <PluginBrandIcon id={source.pluginId} logoUrl={source.logoUrl} Icon={Blocks} />
        </span>
        <span>
          <strong>Connect a source</strong>
          <small>{source.connected ? `${source.name} connected` : `${source.name} is not connected`}</small>
        </span>
        <span className={`evidence-pill ${source.connected ? "connected" : ""}`}>{source.connected ? "Connected" : "Not connected"}</span>
      </div>
      <h3>{options.length ? `Choose a ${noun}` : "Choose what counts as evidence"}</h3>
      {!source.connected ? <p className="field-hint">Reconnect {source.name} in <Link to="/plugins">Plugins</Link> to choose sources.</p> : null}
      {resources.isLoading ? <p className="field-hint">Loading resources…</p> : null}
      {options.length ? <input className="evidence-resource-search ui-field" type="search" aria-label={`Search ${source.name} sources`} name={`search_${source.pluginId}_sources`} autoComplete="off" placeholder={`Search ${noun === "source" ? "sources" : `${noun}s`}`} value={resourceQuery} onChange={(event) => setResourceQuery(event.target.value)} /> : null}
      {options.length ? (
        <ul className="evidence-resource-list">
          {visibleOptions.slice(0, visibleLimit).map((resource) => {
            const checked = selectedResources.includes(resource.resource_id);
            return (
              <li key={resource.resource_id} className={checked ? "evidence-resource-row selected" : "evidence-resource-row"}>
                <label className="evidence-resource-choice">
                  <input
                    type={source.pluginId === "github" ? "radio" : generic ? "radio" : "checkbox"}
                    checked={checked}
                    onChange={() => onToggleResource(resource.resource_id)}
                  />
                  <span className="source-resource-mark"><ResourceMark type={resource.resource_type} /></span>
                  <span className="evidence-resource-copy">
                    <strong>{resource.label}</strong>
                    <small>{source.name}</small>
                  </span>
                  {checked ? <Check className="source-resource-check" aria-hidden="true" /> : null}
                </label>
                {resource.url ? (
                  <a className="evidence-resource-open" href={resource.url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${resource.label} in ${source.name}`}>
                    <ExternalLink size={17} aria-hidden="true" />
                  </a>
                ) : null}
                {checked ? (
                  <div className="source-inline-preview">
                    {preview.isLoading ? <p className="field-hint" role="status">Reading this source…</p> : null}
                    {preview.isError ? <p className="field-hint" role="alert">This source could not be read. Check permission and try again.</p> : null}
                    {preview.data ? (
                      <SourcePreviewView
                        preview={preview.data}
                        selectedMeasurementId={measurementId}
                        trackingLabel={trackingLabel}
                        onSelectMeasurement={(id) => {
                          const measurement = preview.data?.measurements.find((item) => item.id === id);
                          setMeasurementId(id);
                          setTrackingLabel(measurement?.label ?? "");
                        }}
                        onTrackingLabel={setTrackingLabel}
                      />
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {visibleOptions.length > visibleLimit ? (
        <button type="button" className="evidence-resource-more" onClick={() => setVisibleLimit((current) => current + 50)}>
          Show more
        </button>
      ) : null}
      {source.pluginId === "github" ? (
        <label className="evidence-ref-field">
          <span>
            Branch (optional)
          </span>
          <input
            className="ui-field"
            name={`resource-ref-${source.pluginId}`}
            autoComplete="off"
            value={resourceRef}
            onChange={(event) => onResourceRefChange(event.target.value)}
            placeholder={
              source.pluginId === "github" ? "main" : "Leave blank for default scope"
            }
          />
        </label>
      ) : null}
      {generic && !options.length ? (
        <label className="evidence-ref-field">
          <span>Authorized resource ID or bounded query</span>
          <input className="ui-field" value={resourceRef} maxLength={500}
            onChange={(event) => onResourceRefChange(event.target.value)}
            placeholder="Enter the exact resource ID or search query" />
          <small>An exact value here takes precedence over a selected resource. Only the chosen read action and this resource or query will be saved.</small>
        </label>
      ) : null}
      {requiredFields.map((key) => {
        const property = schemaProperties[key];
        const choices = property?.enum ?? [];
        return (
          <label key={key} className="evidence-ref-field">
            <span>{key === "range" ? "Rows to include" : key.replaceAll("_", " ").replace(/^\w/, (letter) => letter.toUpperCase())}</span>
            {choices.length ? (
              <select className="ui-field" value={readArguments[key] ?? ""} onChange={(event) => {
                onArgumentChange(key, event.target.value);
                setPreviewArguments((current) => ({ ...current, [key]: event.target.value }));
              }}>
                <option value="">Select</option>
                {choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
              </select>
            ) : (
              <input className="ui-field" value={readArguments[key] ?? ""} maxLength={500} required
                onChange={(event) => onArgumentChange(key, event.target.value)}
                onBlur={(event) => setPreviewArguments((current) => ({ ...current, [key]: event.target.value.trim() }))}
                placeholder={key === "range" ? "Window this read should include" : "Enter the value this read requires"} />
            )}
          </label>
        );
      })}
      {activityOptions.length && !generic ? (
        <fieldset className="evidence-activity-fieldset">
          <legend>Read activity</legend>
          <div className="evidence-activity-options">
            {activityOptions.map((activity) => (
              <label key={activity.value} className="ui-choice">
                <input
                  type={generic ? "radio" : "checkbox"}
                  checked={selectedActivities.includes(activity.value)}
                  onChange={() => onToggleActivity(activity.value)}
                />
                {activity.label}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}
      {resources.isError && !generic ? <p className="field-hint" role="alert">Could not load available sources. Check access and try again.</p> : null}
      {generic && resources.isError ? <p className="field-hint" role="status">This connection has no safe resource listing. Enter an exact resource ID or bounded query for a compatible read action.</p> : null}
      {source.connected && resources.isSuccess && !options.length && !generic ? <p className="field-hint">No accessible pages or repositories found. Check this connection's access.</p> : null}
      {generic && capabilities.isSuccess && !activityOptions.length ? <p className="field-hint" role="status">No safely scoped read action is available for this connection and its current permissions.</p> : null}
      <button type="button" className="ui-button source-track-action" disabled={approvePending || !source.connected || ((source.pluginId === "github" || source.pluginId === "notion") && !selectedResources.length) || (source.pluginId === "github" && !selectedActivities.length) || (generic && ((options.length ? !preview.data?.records.length || Boolean(preview.data.error) : !resourceRef.trim()) || selectedActivities.length !== 1 || !requiredArgumentsReady))} onClick={() => {
        const chosen = preview.data?.measurements.find((item) => item.id === measurementId);
        const resourceLabel = options.filter((item) => selectedResources.includes(item.resource_id)).map((item) => item.label).join(", ") || resourceRef.trim();
        onApprove(chosen?.ambiguous && trackingLabel.trim() ? trackingLabel.trim() : resourceLabel, Object.fromEntries(Object.entries(readArguments).filter(([key, value]) => key in schemaProperties && value.trim())));
      }}>
        {approvePending ? "Saving…" : "Start tracking"}
      </button>
    </div>
  );
}

export { formatProbability };
