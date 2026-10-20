import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type PluginView,
  type SourcePlannerProposal,
  type SourceRecipeRecord,
  type WorkflowSnapshot,
} from "../../api/client";
import { PluginBrandIcon } from "../../components/plugins/PluginBrandIcon";
import { isPluginConnected, pluginViewToDisplay } from "../../components/plugins/pluginPresentation";
import { AgentProgress } from "../agents/AgentProgress";
import { EvidenceWorkflow } from "./EvidenceWorkflow";
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

function buildSourceCards(plan: SourcePlannerProposal | undefined, plugins: PluginView[]): SourceCardModel[] {
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
    if (!connected && irrelevantIds.has(id)) continue;
    cards.push({
      pluginId: id,
      name: display.name,
      description: display.description,
      logoUrl: plugin.definition.logo_url ?? undefined,
      bucket: connected ? "connected" : "other",
      relevance: irrelevantIds.has(id) ? "low relevance" : connected ? "available" : "not connected",
      rationale:
        plan?.irrelevant.find((item) => item.plugin_id === id)?.rationale ??
        (connected ? "Connected but not prioritized for this goal." : "Connect to include in planning."),
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
  const [repositories, setRepositories] = useState<Record<string, string>>({});
  const [resourceRefs, setResourceRefs] = useState<Record<string, string>>({});
  const [activityTypes, setActivityTypes] = useState<Record<string, string[]>>({});
  const [snapshot, setSnapshot] = useState<WorkflowSnapshot | null>(initialSnapshot);

  const plugins = useQuery({
    queryKey: ["plugins"],
    queryFn: ({ signal }) => api.plugins(signal),
  });
  const sourcePlan = useQuery({
    queryKey: ["evidence-source-plan", goalId],
    queryFn: ({ signal }) => api.evidenceSourcePlan(goalId, signal),
    enabled: Boolean(goalId) && planRequested,
  });
  const recipes = useQuery({
    queryKey: ["evidence-source-recipes", goalId],
    queryFn: ({ signal }) => api.evidenceSourceRecipes(goalId, signal),
    enabled: Boolean(goalId),
  });
  const cards = useMemo(
    () => buildSourceCards(sourcePlan.data, plugins.data ?? []),
    [plugins.data, sourcePlan.data],
  );

  const saveRecipe = useMutation({
    mutationFn: (body: {
      pluginId: string;
      label: string;
      resourceIds: string[];
      activityTypes?: string[];
    }) =>
      api.saveEvidenceSourceRecipe(goalId, body.pluginId, {
        label: body.label,
        resource_ids: body.resourceIds,
        approved: true,
        activity_types: body.activityTypes,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["evidence-source-recipes", goalId] });
    },
  });

  const syncSources = useMutation({
    mutationFn: () => api.syncEvidenceSources(goalId),
    onSuccess: (data) => {
      if ("thread_id" in data) {
        setSnapshot(data);
        onSnapshotChange?.(data);
      }
      void queryClient.invalidateQueries({ queryKey: ["evidence", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["goal", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["market-history", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["what-if-baseline", goalId] });
    },
  });

  const toggleActivity = (pluginId: string, activity: string) => {
    setActivityTypes((current) => {
      const existing = new Set(current[pluginId] ?? []);
      if (existing.has(activity)) existing.delete(activity);
      else existing.add(activity);
      return { ...current, [pluginId]: [...existing] };
    });
  };

  const buildResourceIds = (pluginId: string, card: SourceCardModel) => {
    if (pluginId === "github") {
      const repository = (repositories.github ?? "").trim();
      const branch = (resourceRefs.github ?? "").trim();
      return repository ? [`${repository}${branch ? `@${branch}` : ""}`] : [];
    }
    const base =
      selectedResources[pluginId]?.length
        ? (selectedResources[pluginId] ?? [])
        : card.resources.map((item) => item.resource_id);
    const ref = (resourceRefs[pluginId] ?? "").trim();
    if (!ref) return base;
    return base.map((resourceId) => (resourceId.includes("@") ? resourceId : `${resourceId}@${ref}`));
  };

  const toggleResource = (pluginId: string, resourceId: string) => {
    setSelectedResources((current) => {
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
            {sourcePlan.data?.goal_type ? <span>Type: {sourcePlan.data.goal_type}</span> : null}
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
                          <small>{card.rationale}</small>
                          <span className="evidence-source-meta">
                            <span className={`evidence-pill ${section.key === "recommended" ? "recommended" : ""}`}>
                              {card.relevance}
                            </span>
                            <span className={`evidence-pill ${card.connected ? "connected" : ""}`}>
                              {card.connected ? "Connected" : "Not connected"}
                            </span>
                            {card.lastSyncLabel ? <span className="evidence-pill">{card.lastSyncLabel}</span> : null}
                          </span>
                        </span>
                      </button>
                      {expanded ? (
                        <SourceResourcePanel
                          source={card}
                          selectedResources={selectedResources[card.pluginId] ?? []}
                          resourceRef={resourceRefs[card.pluginId] ?? ""}
                          repository={repositories[card.pluginId] ?? ""}
                          selectedActivities={activityTypes[card.pluginId] ?? []}
                          onResourceRefChange={(value) =>
                            setResourceRefs((current) => ({ ...current, [card.pluginId]: value }))
                          }
                          onRepositoryChange={(value) =>
                            setRepositories((current) => ({ ...current, [card.pluginId]: value }))
                          }
                          onToggleActivity={(activity) => toggleActivity(card.pluginId, activity)}
                          onToggleResource={(resourceId) => toggleResource(card.pluginId, resourceId)}
                          onApprove={() =>
                            saveRecipe.mutate({
                              pluginId: card.pluginId,
                              label: card.pluginId === "github" ? (repositories.github ?? "").trim() : card.resources[0]?.label ?? card.name,
                              resourceIds: buildResourceIds(card.pluginId, card),
                              activityTypes: activityTypes[card.pluginId],
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
              <strong>{savedRecipes.length} approved recipe(s)</strong>
              <ul className="evidence-recipe-list">
                {savedRecipes.map((recipe: SourceRecipeRecord) => (
                  <li key={`${recipe.plugin_id}-${recipe.label}`}>
                    <strong>{recipe.plugin_id}</strong>: {recipe.label}
                    {recipe.steps?.length ? <span className="field-hint"> · {recipe.steps.length} read action(s)</span> : null}
                  </li>
                ))}
              </ul>
            </div>
            <button type="button" disabled={syncSources.isPending} onClick={() => syncSources.mutate()}>
              {syncSources.isPending ? "Syncing…" : "Sync approved sources"}
            </button>
          </div>
        ) : null}

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
  repository,
  selectedActivities,
  onResourceRefChange,
  onRepositoryChange,
  onToggleActivity,
  onToggleResource,
  onApprove,
  approvePending,
}: {
  source: SourceCardModel;
  selectedResources: string[];
  resourceRef: string;
  repository: string;
  selectedActivities: string[];
  onResourceRefChange: (value: string) => void;
  onRepositoryChange: (value: string) => void;
  onToggleActivity: (activity: string) => void;
  onToggleResource: (resourceId: string) => void;
  onApprove: () => void;
  approvePending: boolean;
}) {
  const resources = useQuery({
    queryKey: ["plugin-resources", source.pluginId],
    queryFn: ({ signal }) => api.pluginResources(source.pluginId, signal),
    staleTime: 60_000,
    enabled: source.pluginId !== "github",
  });
  const capabilities = useQuery({
    queryKey: ["plugin-capabilities", source.pluginId],
    queryFn: ({ signal }) => api.pluginCapabilities(source.pluginId, signal),
    staleTime: 60_000,
  });
  const githubActivities = [
    { value: "commits", label: "Commits", tools: ["GITHUB_LIST_COMMITS"] },
    { value: "pull_requests", label: "Pull requests", tools: ["GITHUB_GET_PULL_REQUESTS", "GITHUB_LIST_PULL_REQUESTS"] },
    { value: "issues", label: "Issues", tools: ["GITHUB_LIST_ISSUES_FOR_A_REPOSITORY", "GITHUB_LIST_REPOSITORY_ISSUES"] },
  ];
  const activityOptions = source.pluginId === "github"
    ? githubActivities.filter((activity) => (capabilities.data ?? []).some((item) => activity.tools.includes(item.tool_name ?? "")))
    : (capabilities.data ?? []).slice(0, 6).map((item) => ({ value: item.label.toLowerCase(), label: item.label }));
  const validRepository = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository.trim());
  const rankedPlan = [...source.resources].sort((left, right) => {
    const rank = (item: (typeof source.resources)[number]) =>
      item.recommended || item.goal_relevance === "high" ? 0 : item.goal_relevance === "medium" ? 1 : 2;
    return rank(left) - rank(right);
  });
  const options =
    resources.data?.length
      ? resources.data
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
            };
          })
          .sort((left, right) => Number(right.recommended) - Number(left.recommended))
      : rankedPlan;

  return (
    <div className="evidence-resource-panel">
      <h3>{source.pluginId === "github" ? "GitHub evidence" : "Choose what counts as evidence"}</h3>
      {source.pluginId === "github" ? (
        <label className="evidence-ref-field">
          <span>Repository</span>
          <input value={repository} onChange={(event) => onRepositoryChange(event.target.value)} placeholder="owner/repository" autoComplete="off" />
        </label>
      ) : null}
      {resources.isLoading ? <p className="field-hint">Loading resources…</p> : null}
      {source.pluginId !== "github" && options.length ? (
        <ul className="evidence-resource-list">
          {options.map((resource) => {
            const checked = selectedResources.includes(resource.resource_id);
            return (
              <li key={resource.resource_id}>
                <label>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggleResource(resource.resource_id)}
                  />
                  <strong>{resource.label}</strong>
                  <span>
                    {resource.resource_type ? `${resource.resource_type} · ` : ""}
                    {resource.goal_relevance ? `${resource.goal_relevance} relevance · ` : ""}
                    {resource.rationale}
                    {resource.state_variables?.length ? ` · state: ${resource.state_variables.join(", ")}` : ""}
                    {source.lastSyncLabel ? ` · ${source.lastSyncLabel}` : ""}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      ) : null}
      {source.pluginId === "github" || source.pluginId === "notion" || source.pluginId === "google_sheets" ? (
        <label className="evidence-ref-field">
          <span>
            {source.pluginId === "github"
              ? "Branch (optional)"
              : source.pluginId === "google_sheets"
                ? "Tab or range (optional)"
                : "Page scope (optional)"}
          </span>
          <input
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
      {activityOptions.length ? (
        <fieldset className="evidence-activity-fieldset">
          <legend>Read activity</legend>
          <div className="evidence-activity-options">
            {activityOptions.map((activity) => (
              <label key={activity.value}>
                <input
                  type="checkbox"
                  checked={selectedActivities.includes(activity.value)}
                  onChange={() => onToggleActivity(activity.value)}
                />
                {activity.label}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}
      {source.pluginId === "github" && repository && !validRepository ? <p className="field-hint" role="alert">Enter a repository as owner/name.</p> : null}
      <button type="button" disabled={approvePending || !source.connected || (source.pluginId === "github" && (!validRepository || !selectedActivities.length))} onClick={onApprove}>
        {approvePending ? "Saving…" : "Save source"}
      </button>
    </div>
  );
}

export { formatProbability };
