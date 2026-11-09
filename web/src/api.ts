// Typed client for the Spadesys API. Mirrors api/spadesys/schemas.py.

export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export interface RunStats {
  rows_read: number;
  rows_inserted: number;
  rows_already_loaded: number;
  duplicate_rows_in_file: number;
  columns: number;
  columns_added: string[];
  warnings: string[];
}

export interface Run {
  id: string;
  source_id: string;
  pipeline: string;
  status: RunStatus;
  original_filename: string | null;
  stats: RunStats | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Source {
  id: string;
  name: string;
  kind: string;
  table_name: string;
  row_count: number;
  created_at: string;
  updated_at: string;
  last_run: Run | null;
}

export interface ColumnSchema {
  name: string;
  original_name: string;
  position: number;
  type: "boolean" | "integer" | "decimal" | "date" | "timestamp" | "text";
  nullable: boolean;
  null_count: number;
  distinct_count: number;
  unique: boolean;
  samples: string[];
}

export interface InferredSchema {
  version: number;
  row_count: number;
  columns: ColumnSchema[];
  key_candidates: string[];
}

export interface SourceDetail extends Source {
  inferred_schema: InferredSchema | null;
  runs: Run[];
}

export interface Preview {
  columns: string[];
  rows: unknown[][];
}

export interface ActivityEvent {
  id: number;
  ts: string;
  stage: string;
  message: string;
  source_id: string | null;
  run_id: string | null;
  source_name: string | null;
  detail: Record<string, unknown> | null;
}

export interface Suggestion {
  source_id: string;
  source_name: string;
  table_name: string;
  row_count: number;
  score: number;
  reasons: string[];
  recommended: boolean;
}

export interface FileAnalysis {
  key: string;
  filename: string;
  size: number;
  row_count: number;
  columns: string[];
  preview_rows: unknown[][];
  suggestions: Suggestion[];
  suggested_new_name: string;
  suggested_table_name: string;
  layout: Layout | null;
  layout_text: string;
  layout_notes: string[];
  layout_guessed: boolean; // Spadesys thinks the table doesn't start on row 1
}

/** Where the table is inside a file. Rows are 1-based; header_row 0 = no header row. */
export interface Layout {
  sheet?: string | null;
  header_row: number;
  data_row: number;
  stop: "end" | "blank" | "text";
  stop_text?: string;
}

export interface LayoutPreview {
  ok: boolean;
  error?: string;
  filename: string;
  sheets: string[];
  sheet: string | null;
  grid: string[][];
  total_rows: number;
  guess: Layout;
  layout: Layout;
  layout_text?: string;
  notes?: string[];
  columns?: string[];
  rows?: string[][];
  row_count?: number;
}

export interface StorageFile {
  key: string;
  name: string;
  size: number;
  last_modified: string;
}

export interface StorageFolder {
  bucket: string;
  prefix: string;
  folders: string[];
  files: StorageFile[];
}

export interface StoragePreview {
  info: { key: string; size: number; last_modified: string; content_type: string | null; original_filename: string | null };
  lines: string[];
  truncated: boolean;
  is_text: boolean;
}

export interface FieldSpec {
  name: string;
  type: string;
  generator: string;
  params: Record<string, string | number>;
  null_percent: number;
  unique: boolean;
  max_length: number | null;
  db_type: string | null;
  nullable: boolean;
  reason: string | null;
  warning: string | null;
}

export interface GeneratorInfo {
  key: string;
  label: string;
  group: string;
  types: string[];
  defaults: Record<string, string | number>;
}

export interface Catalog {
  types: { key: string; label: string }[];
  generators: GeneratorInfo[];
}

export interface DbConnection {
  id: string;
  name: string;
  kind: "postgresql" | "mysql";
  host: string;
  port: number;
  database: string;
  username: string;
}

export type DbConnectionIn = Omit<DbConnection, "id"> & { password: string };

export interface GenerateBody {
  fields: FieldSpec[];
  rows: number;
  connection_id?: string | null;
  filename?: string;
}

export interface PipelineFile {
  name: string;
  size: number;
  modified: string;
  matches?: boolean;
  path?: string;
}

/** Where files show up and the raw table they land in. Shared by extracts and (read-only) pipelines. */
export interface ExtractPlace {
  folder: string;
  layout: Layout | null;
  layout_text: string;
  location: string;
  bucket: string | null;
  prefix: string | null;
  pattern: string;
  waiting: number;
  last_run: Run | null;
}

export interface Extract extends ExtractPlace {
  id: string;
  name: string;
  kind: "folder" | "storage";
  table: TableRef | null;
  created_at: string;
  used_by: { id: string; name: string; mode: "manual" | "watch" }[];
}

export interface ExtractDetail extends Extract {
  files_waiting: PipelineFile[];
  files_done: PipelineFile[];
  runs: Run[];
}

export interface TableRef { source_id: string; name: string; table_name: string; row_count: number }

export interface ExtractIn {
  name: string;
  kind: "folder" | "storage";
  bucket?: string;
  prefix?: string;
  pattern: string;
  source_id?: string | null;
  new_table_name?: string | null;
  layout?: Layout | null;
}

export interface Pipeline extends Partial<ExtractPlace> {
  id: string;
  name: string;
  extract: { id: string; name: string; kind: "folder" | "storage" } | null;
  source_kind: "folder" | "storage" | null;
  destination: TableRef | null;
  mode: "manual" | "watch";
  watch_seconds: number;
  last_checked_at: string | null;
  created_at: string;
  waiting: number;
}

export interface PipelineDetail extends Pipeline {
  files_waiting: PipelineFile[];
  files_done: PipelineFile[];
  runs: Run[];
}

export interface PipelineIn {
  name: string;
  extract_id?: string;
  source_kind?: "folder" | "storage";
  bucket?: string;
  prefix?: string;
  pattern?: string;
  destination_source_id?: string | null;
  new_table_name?: string | null;
  layout?: Layout | null;
  mode: "manual" | "watch";
  watch_seconds: number;
}

export type StepOp = "split" | "parse_name" | "join" | "clean" | "rename" | "drop" | "stack" | "dedupe";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type TransformStep = { op: StepOp; disabled?: boolean; [k: string]: any };
export interface ColInfo { name: string; type: string }
export interface TableInfo { full: string; schema: string; name: string; columns: ColInfo[]; made_by: { id: string; name: string } | null }

export interface Transform {
  id: string;
  name: string;
  description: string | null;
  input_table: string;
  steps: TransformStep[];
  output_table: string;
  output_full: string;
  last_run_at: string | null;
  last_rows: number | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface TransformBody { name: string; description?: string | null; input_table: string; steps: TransformStep[]; output_table: string }

export interface TransformPreview {
  ok: boolean;
  sql?: string;
  columns?: ColInfo[];
  step_columns?: ColInfo[][];
  rows?: unknown[][];
  row_count?: number;
  error?: { step: number | null; message: string };
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  checks: Record<string, string>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/health"),
  sources: () => request<Source[]>("/sources"),
  source: (id: string) => request<SourceDetail>(`/sources/${id}`),
  preview: (id: string, limit = 50) => request<Preview>(`/sources/${id}/preview?limit=${limit}`),
  deleteSource: (id: string) => request<void>(`/sources/${id}`, { method: "DELETE" }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Source>("/sources", { method: "POST", body: form });
  },
  reload: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Run>(`/sources/${id}/runs`, { method: "POST", body: form });
  },
  events: ({ afterId = 0, sourceId }: { afterId?: number; sourceId?: string } = {}) =>
    request<ActivityEvent[]>(`/events?after_id=${afterId}${sourceId ? `&source_id=${sourceId}` : ""}`),
  stageUpload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<FileAnalysis>("/uploads", { method: "POST", body: form });
  },
  analyzeStored: (key: string) => request<FileAnalysis>(`/uploads/analyze?key=${encodeURIComponent(key)}`),
  loadStaged: (body: { key: string; source_id?: string; new_name?: string; layout?: Layout | null }) => request<Source>("/uploads/load", json(body)),
  previewStoredLayout: (key: string, layout: Layout | null, bucket?: string) =>
    request<LayoutPreview>("/layouts/preview", json({ key, layout, bucket })),
  previewFileLayout: (file: File, layout: Layout | null) => {
    const form = new FormData();
    form.append("file", file);
    if (layout) form.append("layout", JSON.stringify(layout));
    return request<LayoutPreview>("/layouts/preview-file", { method: "POST", body: form });
  },
  extractSamples: (id: string) => request<{ ref: string; label: string }[]>(`/extracts/${id}/samples`),
  extractLayoutPreview: (id: string, ref: string, layout: Layout | null) =>
    request<LayoutPreview>(`/extracts/${id}/layout-preview`, json({ ref, layout })),
  buckets: () => request<{ buckets: string[]; default: string }>("/storage/buckets"),
  listFolder: (bucket: string, prefix: string) =>
    request<StorageFolder>(`/storage/list?bucket=${encodeURIComponent(bucket)}&prefix=${encodeURIComponent(prefix)}`),
  previewObject: (bucket: string, key: string) =>
    request<StoragePreview>(`/storage/preview?bucket=${encodeURIComponent(bucket)}&key=${encodeURIComponent(key)}`),
  downloadUrl: (bucket: string, key: string) =>
    `/api/storage/download?bucket=${encodeURIComponent(bucket)}&key=${encodeURIComponent(key)}`,
  downloadFolderUrl: (bucket: string, prefix: string) =>
    `/api/storage/download-folder?bucket=${encodeURIComponent(bucket)}&prefix=${encodeURIComponent(prefix)}`,
  createStorageFolder: (bucket: string, prefix: string, name: string) =>
    request<{ prefix: string }>("/storage/folders", json({ bucket, prefix, name })),
  uploadToStorage: (bucket: string, prefix: string, files: File[]) => {
    const form = new FormData();
    form.append("bucket", bucket);
    form.append("prefix", prefix);
    files.forEach((f) => form.append("files", f));
    return request<{ saved: { key: string; name: string; renamed: boolean }[] }>("/storage/upload", { method: "POST", body: form });
  },
  storageFolderSummary: (bucket: string, prefix: string) =>
    request<{ files: number; size: number }>(`/storage/folder-summary?bucket=${encodeURIComponent(bucket)}&prefix=${encodeURIComponent(prefix)}`),
  deleteStorageFolder: (bucket: string, prefix: string) =>
    request<{ deleted: number }>(`/storage/folder?bucket=${encodeURIComponent(bucket)}&prefix=${encodeURIComponent(prefix)}`, { method: "DELETE" }),
  deleteStorageObject: (bucket: string, key: string) =>
    request<{ deleted: number }>(`/storage/object?bucket=${encodeURIComponent(bucket)}&key=${encodeURIComponent(key)}`, { method: "DELETE" }),
  catalog: () => request<Catalog>("/devdata/catalog"),
  recommend: (text: string) => request<FieldSpec[]>("/devdata/recommend", json({ text })),
  connections: () => request<DbConnection[]>("/connections"),
  testConnection: (c: DbConnectionIn) => request<{ ok: boolean; version?: string; error?: string; hint?: string; suggested_host?: string }>("/connections/test", json(c)),
  saveConnection: (c: DbConnectionIn) => request<DbConnection>("/connections", json(c)),
  deleteConnection: (id: string) => request<void>(`/connections/${id}`, { method: "DELETE" }),
  tables: (id: string) => request<{ schema: string; tables: string[] }[]>(`/connections/${id}/tables`),
  describeTable: (id: string, schema: string, table: string) =>
    request<FieldSpec[]>(`/connections/${id}/tables/${encodeURIComponent(schema)}/${encodeURIComponent(table)}`),
  previewDevData: (b: GenerateBody) => request<Preview>("/devdata/preview", json(b)),
  devDataToStorage: (b: GenerateBody) => request<{ key: string; size: number }>("/devdata/to-storage", json(b)),
  insertDevData: (b: GenerateBody & { connection_id: string; schema_name: string; table: string }) =>
    request<{ inserted: number }>("/devdata/insert", json(b)),
  downloadDevData: async (b: GenerateBody) => {
    const res = await fetch("/api/devdata/download", json(b));
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail));
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = b.filename ?? "dev_data.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  },
  cloudbeaver: () => request<{ up: boolean; connections: string[] }>("/databases/cloudbeaver"),
  pipelines: () => request<Pipeline[]>("/pipelines"),
  pipeline: (id: string) => request<PipelineDetail>(`/pipelines/${id}`),
  createPipeline: (b: PipelineIn) => request<PipelineDetail>("/pipelines", json(b)),
  updatePipeline: (id: string, b: { name?: string; extract_id?: string; mode?: "manual" | "watch"; watch_seconds?: number }) =>
    request<PipelineDetail>(`/pipelines/${id}`, { ...json(b), method: "PATCH" }),
  deletePipeline: (id: string) => request<void>(`/pipelines/${id}`, { method: "DELETE" }),
  runPipeline: (id: string) => request<Run[]>(`/pipelines/${id}/run`, { method: "POST" }),
  addPipelineFile: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ name: string }>(`/pipelines/${id}/files`, { method: "POST", body: form });
  },
  pipelineEvents: (id: string, afterId = 0) => request<ActivityEvent[]>(`/pipelines/${id}/events?after_id=${afterId}`),
  transforms: () => request<Transform[]>("/transforms"),
  transformTables: () => request<TableInfo[]>("/transforms/tables"),
  previewTransform: (b: { input_table: string; steps: TransformStep[]; output_table?: string; limit?: number }) =>
    request<TransformPreview>("/transforms/preview", json(b)),
  createTransform: (b: TransformBody) => request<Transform>("/transforms", json(b)),
  saveTransform: (id: string, b: TransformBody) => request<Transform>(`/transforms/${id}`, { ...json(b), method: "PUT" }),
  deleteTransform: (id: string, dropTable = false) => request<void>(`/transforms/${id}?drop_table=${dropTable}`, { method: "DELETE" }),
  runTransform: (id: string) => request<{ rows: number; table: string }>(`/transforms/${id}/run`, { method: "POST" }),
  transformEvents: (id: string, afterId = 0) => request<ActivityEvent[]>(`/transforms/${id}/events?after_id=${afterId}`),
  extracts: () => request<Extract[]>("/extracts"),
  extract: (id: string) => request<ExtractDetail>(`/extracts/${id}`),
  createExtract: (b: ExtractIn) => request<ExtractDetail>("/extracts", json(b)),
  updateExtract: (id: string, b: { name?: string; pattern?: string; source_id?: string; layout?: Layout; reset_layout?: boolean }) =>
    request<ExtractDetail>(`/extracts/${id}`, { ...json(b), method: "PATCH" }),
  deleteExtract: (id: string) => request<void>(`/extracts/${id}`, { method: "DELETE" }),
  runExtract: (id: string) => request<Run[]>(`/extracts/${id}/run`, { method: "POST" }),
  addExtractFile: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ name: string }>(`/extracts/${id}/files`, { method: "POST", body: form });
  },
  extractEvents: (id: string, afterId = 0) => request<ActivityEvent[]>(`/extracts/${id}/events?after_id=${afterId}`),
  retry: (runId: string) => request<Run>(`/runs/${runId}/retry`, { method: "POST" }),
  generateCommerce: (opts: { customers?: number; items?: number; orders?: number } = {}) =>
    request<Source[]>("/generate/commerce", json(opts)),
};

export const isActive = (r: Run | null | undefined) => r?.status === "queued" || r?.status === "running";
