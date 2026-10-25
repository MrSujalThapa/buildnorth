import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { api } from "../../api/client";
import { ResourceMark, SourcePreviewView, sourceNoun } from "../../features/goals/SourcePreview";

export function PluginResourcePreview({ pluginId }: { pluginId: string }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const resources = useQuery({
    queryKey: ["plugin-resources", pluginId],
    queryFn: ({ signal }) => api.pluginResources(pluginId, signal),
    staleTime: 60_000,
  });
  const options = (resources.data ?? []).map((item) => ({
    resource_id: item.uri.replace(/^composio:\/\/[^/]+\//, "") || item.name,
    label: item.name,
    resource_type: item.resource_type || "resource",
  }));
  const noun = sourceNoun(options.map((item) => item.resource_type));
  const visible = options.filter((item) => item.label.toLowerCase().includes(query.trim().toLowerCase()));
  const selected = options.find((item) => item.resource_id === selectedId) ?? null;
  const preview = useQuery({
    queryKey: ["plugin-preview", pluginId, selected?.resource_id, {}],
    queryFn: () => api.previewPluginSource(pluginId, {
      resource_id: selected?.resource_id ?? "",
      resource_title: selected?.label,
      resource_type: selected?.resource_type,
      arguments: {},
    }),
    enabled: Boolean(selected),
    staleTime: 60_000,
  });

  return (
    <section className="plugin-source-preview">
      <h3>Preview a {noun}</h3>
      {resources.isLoading ? <p className="field-hint" role="status">Loading sources…</p> : null}
      {resources.isError ? <p className="field-hint" role="alert">Sources could not be listed. Check this connection's permission and try again.</p> : null}
      {resources.isSuccess && !options.length ? <p className="field-hint">No resources were returned for this connection.</p> : null}
      {options.length > 6 ? (
        <input
          className="evidence-resource-search ui-field"
          type="search"
          aria-label={`Search ${noun}s`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={`Search ${noun}s`}
        />
      ) : null}
      {visible.length ? (
        <ul className="evidence-resource-list">
          {visible.slice(0, 8).map((resource) => {
            const checked = resource.resource_id === selected?.resource_id;
            return (
              <li key={resource.resource_id} className={checked ? "evidence-resource-row selected" : "evidence-resource-row"}>
                <label className="evidence-resource-choice">
                  <input
                    type="radio"
                    name={`${pluginId}-preview-resource`}
                    checked={checked}
                    onChange={() => setSelectedId(resource.resource_id)}
                  />
                  <span className="source-resource-mark"><ResourceMark type={resource.resource_type} /></span>
                  <span className="evidence-resource-copy">
                    <strong>{resource.label}</strong>
                  </span>
                  {checked ? <Check className="source-resource-check" aria-hidden="true" /> : null}
                </label>
                {checked ? (
                  <div className="source-inline-preview">
                    {preview.isLoading ? <p className="field-hint" role="status">Reading this source…</p> : null}
                    {preview.isError ? <p className="field-hint" role="alert">This source could not be read. Check permission and try again.</p> : null}
                    {preview.data ? (
                      <SourcePreviewView
                        preview={preview.data}
                        selectedMeasurementId={preview.data.measurements[0]?.id ?? null}
                        trackingLabel={preview.data.measurements[0]?.label ?? ""}
                        onSelectMeasurement={() => undefined}
                        onTrackingLabel={() => undefined}
                      />
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
