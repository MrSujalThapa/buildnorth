import { useState } from "react";
import { Activity, Check, FileText, Mail, Table2 } from "lucide-react";
import type { SourcePreview, SourcePreviewRecord } from "../../api/client";
import "./evidence.css";

const PREVIEW_LIMIT = 4;

export function sourceNoun(types: string[]): string {
  const nouns = types.map(humanizeType).filter((item) => item !== "source");
  if (!nouns.length) return "source";
  const noun = nouns[0];
  return noun && nouns.every((item) => item === noun) ? noun : "source";
}

function humanizeType(type: string): string {
  const value = type.toLowerCase();
  if (value.includes("spreadsheet")) return "spreadsheet";
  if (value.includes("message") || value.includes("mail")) return "message";
  if (value.includes("document") || value.includes("page")) return "document";
  if (value.includes("repo")) return "repository";
  if (value === "private" || value === "public" || value === "resource" || value === "") return "source";
  return value.replaceAll("_", " ");
}

function formatMeasurement(value: number, unit?: string | null): string {
  const rendered = Number.isInteger(value) ? String(value) : String(value);
  return unit ? `${rendered} ${unit}` : rendered;
}

export function SourcePreviewView({
  preview,
  selectedMeasurementId,
  trackingLabel,
  onSelectMeasurement,
  onTrackingLabel,
}: {
  preview: SourcePreview;
  selectedMeasurementId: string | null;
  trackingLabel: string;
  onSelectMeasurement: (id: string) => void;
  onTrackingLabel: (value: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const selected = preview.measurements.find((item) => item.id === selectedMeasurementId) ?? preview.measurements[0];
  const visible = selected?.unit || selected?.label
    ? preview.records.filter((record) => {
        if (record.numeric_value == null) return true;
        if (!selected) return true;
        return (record.metric || "Measurement") === selected.label && (record.unit ?? null) === (selected.unit ?? null);
      })
    : preview.records;
  const shown = expanded ? visible : visible.slice(0, PREVIEW_LIMIT);
  const hiddenCount = Math.max(0, visible.length - PREVIEW_LIMIT);
  const shownMeasurements = shown.filter((record) => record.kind === "measurement");
  const shownActivities = shown.filter((record) => record.kind === "activity");
  const shownMessages = shown.filter((record) => record.kind === "message");
  const shownDocuments = shown.filter((record) => record.kind === "document");
  const shownRecords = shown.filter((record) => record.kind === "record");

  return (
    <div className="source-preview">
      <h3>Confirm what this represents</h3>
      {preview.measurements.length ? (
        <div className="source-track-list">
          {preview.measurements.map((item) => {
            const pressed = item.id === (selected?.id ?? "");
            return (
              <button
                key={item.id}
                type="button"
                className={pressed ? "source-track-card selected" : "source-track-card"}
                aria-pressed={pressed}
                onClick={() => onSelectMeasurement(item.id)}
              >
                <span>
                  {pressed && item.ambiguous ? (
                    <input
                      aria-label="Measurement label"
                      value={trackingLabel}
                      onChange={(event) => onTrackingLabel(event.target.value)}
                      onClick={(event) => event.stopPropagation()}
                    />
                  ) : <strong>{item.label}</strong>}
                  <small>{item.detail}</small>
                </span>
                {pressed ? <Check aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>
      ) : (
        <p className="field-hint">{preview.notice ?? "No measurements were detected in this source."}</p>
      )}
      <div className="source-detected">
        <div className="source-detected-heading">
          <span>Preview of detected data</span>
          <small>Unverified</small>
        </div>
        {preview.error ? <p role="alert">{preview.error}</p> : null}
        {!preview.error && !preview.records.length ? <p>No records were returned for this source.</p> : null}
        {preview.columns?.length ? <StructuredTable columns={preview.columns} records={shown} /> : null}
        {!preview.columns?.length && shownMeasurements.length ? <MeasurementTable records={shownMeasurements} /> : null}
        {!preview.columns?.length && shownActivities.map((record) => <ActivityCard key={record.title + (record.timestamp ?? "")} record={record} />)}
        {!preview.columns?.length && shownMessages.map((record) => <MessageCard key={(record.actor ?? "") + record.title} record={record} />)}
        {!preview.columns?.length && shownDocuments.map((record) => <DocumentCard key={record.title} record={record} />)}
        {!preview.columns?.length && shownRecords.map((record) => <RecordCard key={record.title + (record.timestamp ?? "")} record={record} />)}
        {hiddenCount && !expanded ? (
          <button type="button" className="source-preview-more" onClick={() => setExpanded(true)}>
            Show {hiddenCount} more
          </button>
        ) : null}
      </div>
    </div>
  );
}

function MeasurementTable({ records }: { records: SourcePreviewRecord[] }) {
  const metrics = new Set(records.map((record) => record.metric).filter(Boolean));
  const rows = records.filter((record) => record.numeric_value != null);
  return (
    <table className="source-preview-table">
      <caption>Detected measurements</caption>
      <tbody>
        {rows.map((record, index) => (
          <tr key={`${record.timestamp ?? record.title}-${index}`}>
            <th scope="row">{record.timestamp || record.title}</th>
            {metrics.size > 1 ? <td>{record.metric}</td> : null}
            <td>{formatMeasurement(record.numeric_value ?? 0, record.unit)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function StructuredTable({ columns, records }: { columns: string[]; records: SourcePreviewRecord[] }) {
  const rows = records.filter((record) => (record.cells ?? []).some((cell) => cell.trim()));
  return (
    <table className="source-preview-table source-preview-grid">
      <thead>
        <tr>
          {columns.map((column) => <th key={column} scope="col">{column}</th>)}
        </tr>
      </thead>
      <tbody>
        {rows.map((record, index) => (
          <tr key={`${record.title}-${index}`}>
            {columns.map((column, cellIndex) => (
              <td key={column}>{record.cells?.[cellIndex] ?? ""}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ActivityCard({ record }: { record: SourcePreviewRecord }) {
  return (
    <article className="source-record-card">
      <Activity aria-hidden="true" />
      <header>
        <strong>{record.title}</strong>
        {record.timestamp ? <time>{record.timestamp}</time> : null}
      </header>
      {record.metrics?.length ? (
        <ul>
          {record.metrics.map((metric) => (
            <li key={metric.label}>{metric.label}: {formatMeasurement(metric.value, metric.unit)}</li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function MessageCard({ record }: { record: SourcePreviewRecord }) {
  return (
    <article className="source-record-card">
      <Mail aria-hidden="true" />
      <header>
        <strong>{record.title}</strong>
        {record.timestamp ? <time>{record.timestamp}</time> : null}
      </header>
      {record.actor ? <p>{record.actor}</p> : null}
      {record.text ? <p>{record.text}</p> : null}
    </article>
  );
}

function DocumentCard({ record }: { record: SourcePreviewRecord }) {
  const repeated = Boolean(record.text && sameText(record.title, record.text));
  return (
    <article className="source-record-card">
      <FileText aria-hidden="true" />
      <header>
        {repeated ? null : <strong>{record.title}</strong>}
        {record.timestamp ? <time>{record.timestamp}</time> : null}
      </header>
      {record.text ? <Excerpt text={record.text} /> : null}
    </article>
  );
}

function RecordCard({ record }: { record: SourcePreviewRecord }) {
  const extra = (record.cells ?? []).filter((cell) => cell && cell !== record.title);
  return (
    <article className="source-record-card">
      <header>
        <strong>{record.title}</strong>
        {record.timestamp ? <time>{record.timestamp}</time> : null}
      </header>
      {record.text && !sameText(record.title, record.text) ? <Excerpt text={record.text} /> : null}
      {extra.length && !record.text ? <p>{extra.join(" · ")}</p> : null}
    </article>
  );
}

function Excerpt({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (text.length <= 140 || open) return <p>{text}</p>;
  return (
    <p>
      {text.slice(0, 140).trimEnd()}…
      <button type="button" className="source-preview-more" onClick={() => setOpen(true)}>Expand</button>
    </p>
  );
}

function sameText(title: string, text: string): boolean {
  const head = title.replace(/…$/, "").trim();
  return Boolean(head) && (text === title || text.startsWith(head));
}

export function ResourceMark({ type }: { type: string }) {
  const noun = humanizeType(type);
  if (noun === "message") return <Mail aria-hidden="true" />;
  if (noun === "document") return <FileText aria-hidden="true" />;
  if (noun === "spreadsheet") return <Table2 aria-hidden="true" />;
  return <Table2 aria-hidden="true" />;
}
