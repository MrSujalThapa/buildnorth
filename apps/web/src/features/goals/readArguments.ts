export type ReadArgumentSchema = {
  properties?: Record<string, { type?: string; enum?: string[]; description?: string }>;
  required?: string[];
  parameters?: ReadArgumentSchema;
};

const PAGE_ARGUMENT_KEYS = new Set([
  "page",
  "limit",
  "page_size",
  "per_page",
  "max_results",
  "maxResults",
]);

const RESOURCE_ARGUMENT = /(^|_)(id|query|channel|q)$|calendarId|spreadsheetId/;

export function schemaBody(schema: ReadArgumentSchema | null | undefined): ReadArgumentSchema {
  return schema?.parameters ?? schema ?? {};
}

export function additionalRequiredArguments(schema: ReadArgumentSchema | undefined): string[] {
  const required = schemaBody(schema).required ?? [];
  return required.filter((key) => !PAGE_ARGUMENT_KEYS.has(key) && !RESOURCE_ARGUMENT.test(key));
}
