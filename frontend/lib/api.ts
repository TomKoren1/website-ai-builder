const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// TS interfaces mirror the backend's Pydantic schemas field-for-field
// (snake_case included) — deliberately not remapped to camelCase, so
// there's no translation layer to keep in sync as the API evolves.

export interface User {
  id: string;
  email: string;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  git_repo_path: string;
  created_at: string;
}

export interface ApiKey {
  id: string;
  provider: string;
  display_hint: string;
  created_at: string;
  last_used_at: string | null;
}

export interface Domain {
  id: string;
  project_id: string;
  domain_name: string;
  s3_bucket_name: string;
  verified: boolean;
  created_at: string;
}

export interface FileChange {
  path: string;
  content: string;
}

export interface ChatResponse {
  reply: string;
  proposed_files: FileChange[];
}

export interface Deployment {
  id: string;
  project_id: string;
  git_commit_sha: string;
  status: string;
  created_at: string;
  deployed_at: string | null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function getCookie(name: string): string | null {
  // The CSRF cookie is deliberately non-httpOnly so this can read it —
  // see backend/app/security/csrf.py for why that's safe.
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

const STATE_CHANGING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);

  if (options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (STATE_CHANGING_METHODS.has(method)) {
    const csrfToken = getCookie("csrf_token");
    if (csrfToken) {
      headers.set("X-CSRF-Token", csrfToken);
    }
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    method,
    headers,
    credentials: "include", // send/receive our httpOnly auth cookies cross-origin
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const body = isJson ? await response.json() : undefined;

  if (!response.ok) {
    const detail =
      (typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail)) ??
      response.statusText;
    throw new ApiError(response.status, detail);
  }

  return body as T;
}

// --- auth ---

export const login = (email: string, password: string) =>
  request<{ access_token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const register = (email: string, password: string) =>
  request<{ access_token: string }>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const logout = () => request<void>("/auth/logout", { method: "POST" });

export const me = () => request<User>("/auth/me");

// --- projects ---

export const listProjects = () => request<Project[]>("/projects");

export const createProject = (name: string) =>
  request<Project>("/projects", { method: "POST", body: JSON.stringify({ name }) });

export const getProject = (id: string) => request<Project>(`/projects/${id}`);

// --- api keys ---

export const listApiKeys = () => request<ApiKey[]>("/api-keys");

export const createApiKey = (provider: string, api_key: string) =>
  request<ApiKey>("/api-keys", { method: "POST", body: JSON.stringify({ provider, api_key }) });

export const deleteApiKey = (id: string) => request<void>(`/api-keys/${id}`, { method: "DELETE" });

// --- domains ---

export const createDomain = (project_id: string, domain_name: string, s3_bucket_name: string) =>
  request<Domain>("/domains", {
    method: "POST",
    body: JSON.stringify({ project_id, domain_name, s3_bucket_name }),
  });

// --- chat / push ---

export interface MessageOut {
  role: string;
  content: string;
  created_at: string;
}

export const getMessages = (projectId: string) =>
  request<MessageOut[]>(`/projects/${projectId}/messages`);

export const chat = (projectId: string, provider: string, message: string) =>
  request<ChatResponse>(`/projects/${projectId}/chat`, {
    method: "POST",
    body: JSON.stringify({ provider, message }),
  });

export const push = (projectId: string, files: FileChange[], commit_message: string) =>
  request<Deployment>(`/projects/${projectId}/push`, {
    method: "POST",
    body: JSON.stringify({ files, commit_message }),
  });
