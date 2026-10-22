export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // no JSON body
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const postJson = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

// -- auth ---------------------------------------------------------------

export interface StatusResp {
  unlocked: boolean;
}

export const getStatus = () => request<StatusResp>("/status");

export const unlock = (passphrase: string, create: boolean, dbPath?: string) =>
  postJson<{ unlocked: boolean }>("/unlock", {
    passphrase,
    create,
    db_path: dbPath || null,
  });

export const lock = () => postJson<{ unlocked: boolean }>("/lock", {});

// -- categories -----------------------------------------------------------

export interface CategoriesResp {
  toggles: Record<string, boolean>;
  defaults: Record<string, boolean>;
}

export const getCategories = () => request<CategoriesResp>("/categories");

export const setCategory = (category: string, enabled: boolean) =>
  postJson<{ toggles: Record<string, boolean> }>("/categories", { category, enabled });

// -- terms ------------------------------------------------------------------

export interface TermsResp {
  terms: string[];
}

export const listTerms = () => request<TermsResp>("/terms");

export const addTerm = (term: string) =>
  postJson<{ added: boolean; terms: string[] }>("/terms", { term });

export const removeTerm = (term: string) =>
  request<{ removed: boolean; terms: string[] }>(`/terms?term=${encodeURIComponent(term)}`, {
    method: "DELETE",
  });

// -- redact: text -----------------------------------------------------------

export interface Detection {
  start: number;
  end: number;
  entity_type: string;
  text: string;
}

export const redactPreview = (text: string) =>
  postJson<Detection[]>("/redact/preview", { text });

export interface ConfirmResp {
  text: string;
  replacements: number;
  by_type: Record<string, number>;
}

export const redactConfirm = (
  text: string,
  detections: { start: number; end: number; entity_type: string }[]
) => postJson<ConfirmResp>("/redact/confirm", { text, detections });

// -- reveal -------------------------------------------------------------------

export const reveal = (text: string) =>
  postJson<{ text: string; restored: number }>("/reveal", { text });

// -- files ----------------------------------------------------------------------

export interface UploadTextResp {
  mode: "text";
  text: string;
}

export interface UploadFileResp {
  mode: "file";
  status: "redacted" | "partial" | "skipped" | "failed";
  reason: string | null;
  counts: Record<string, number>;
  notes: string[];
  download_token: string | null;
  filename: string;
}

export async function uploadFile(file: File): Promise<UploadTextResp | UploadFileResp> {
  const form = new FormData();
  form.append("file", file);
  return request("/redact/upload", { method: "POST", body: form });
}

export const downloadUrl = (token: string) => `/api/redact/download/${token}`;

// -- batch ------------------------------------------------------------------------

export interface BatchFileEntry {
  source: string;
  output: string | null;
  status: string;
  reason: string | null;
  counts: Record<string, number>;
  notes: string[];
}

export interface BatchResp {
  input_dir: string;
  output_dir: string;
  summary: Record<string, number>;
  files: BatchFileEntry[];
}

export const runBatch = (inputDir: string, outputDir: string) =>
  postJson<BatchResp>("/batch", { input_dir: inputDir, output_dir: outputDir });

// -- audit --------------------------------------------------------------------------

export interface AuditEntry {
  id: number;
  ts: string;
  action: string;
  doc: string | null;
  detail: Record<string, unknown>;
  prev_hash: string;
  hash: string;
}

export interface AuditResp {
  chain_valid: boolean;
  entries: AuditEntry[];
}

export const getAudit = () => request<AuditResp>("/audit");

// -- wipe -----------------------------------------------------------------------------

export const wipe = () => postJson<{ wiped: boolean }>("/wipe", { confirm: true });
