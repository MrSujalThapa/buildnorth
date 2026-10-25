import { Check, FileText, Mail, Table2 } from "lucide-react";
import type { SourcePreview, SourcePreviewRecord } from "../../api/client";

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
  const selected = preview.measurements.find((item) => item.id === selectedMeasurementId) ?? preview.measurements[0];
  const visible = selected?.unit || selected?.label
    ? preview.records.filter((record) => {
        if (record.numeric_value == null) return true;
        if (!selected) return true;
        return (record.metric || "Measurement") === selected.label && (record.unit ?? null) === (selected.unit ?? null);
      })
    : preview.records;
  const measurements = visible.filter((record) => record.kind === "measurement");
  const activities = visible.filter((record) => record.kind === "activity");
  const messages = visible.filter((record) => record.kind === "message");
  const documents = visible.filter((record) => record.kind === "document");
  const records = visible.filter((record) => record.kind === "record");

  return (
    <div className="source-preview">
      <h3>What would you like to track?</h3>
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
        <p className="field-hint">No measurements were detected in this source.</p>
      )}
      <div className="source-detected">
        <div className="source-detected-heading">
          <span>Preview of detected data</span>
          <small>Unverified</small>
        </div>
        {preview.error ? <p role="alert">{preview.error}</p> : null}
        {!preview.error && !preview.records.length ? <p>No records were returned for this source.</p> : null}
        {measurements.length ? <MeasurementTable records={measurements} /> : null}
        {activities.map((record) => <ActivityCard key={record.title + (record.timestamp ?? "")} record={record} />)}
        {messages.map((record) => <MessageCard key={(record.actor ?? "") + record.title} record={record} />)}
        {documents.map((record) => <DocumentCard key={record.title} record={record} />)}
        {records.map((record) => <RecordCard key={record.title + (record.timestamp ?? "")} record={record} />)}
      </div>
    </div>
  );
}

function MeasurementTable({ records }: { records: SourcePreviewRecord[] }) {
  const metrics = new Set(records.map((record) => record.metric).filter(Boolean));
  return (
    <table className="source-preview-table">
      <caption>Detected measurements</caption>
      <tbody>
        {records.map((record, index) => (
          <tr key={`${record.timestamp ?? record.title}-${index}`}>
            <th scope="row">{record.timestamp || record.title}</th>
            {metrics.size > 1 ? <td>{record.metric}</td> : null}
            <td>{record.numeric_value == null ? record.text : formatMeasurement(record.numeric_value, record.unit)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ActivityCard({ record }: { record: SourcePreviewRecord }) {
  return (
    <article className="source-record-card">
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
  return (
    <article className="source-record-card">
      <header><strong>{record.title}</strong></header>
      {record.text ? <p>{record.text}</p> : null}
    </article>
  );
}

function RecordCard({ record }: { record: SourcePreviewRecord }) {
  return (
    <article className="source-record-card">
      <header>
        <strong>{record.title}</strong>
        {record.timestamp ? <time>{record.timestamp}</time> : null}
      </header>
      {record.text ? <p>{record.text}</p> : null}
    </article>
  );
}

export function ResourceMark({ type }: { type: string }) {
  const noun = humanizeType(type);
  if (noun === "message") return <Mail aria-hidden="true" />;
  if (noun === "document") return <FileText aria-hidden="true" />;
  if (noun === "spreadsheet") return <Table2 aria-hidden="true" />;
  return <Table2 aria-hidden="true" />;
}
