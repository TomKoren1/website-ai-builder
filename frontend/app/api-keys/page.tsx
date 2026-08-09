"use client";

import { useEffect, useState, type FormEvent } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import * as api from "@/lib/api";
import type { ApiKey } from "@/lib/api";
import { ApiError } from "@/lib/api";

function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [provider, setProvider] = useState("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listApiKeys().then(setKeys).catch(() => setKeys([]));
  }, []);

  async function handleAdd(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const created = await api.createApiKey(provider, apiKey);
      setKeys((prev) => [...(prev ?? []), created]);
      setApiKey(""); // clear immediately — no reason to leave it sitting in the form
    } catch (err) {
      // A 409 here means "you already have a key for this provider" —
      // the backend enforces one key per (user, provider).
      setError(err instanceof ApiError ? err.detail : "Failed to add key");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: string) {
    await api.deleteApiKey(id);
    setKeys((prev) => (prev ?? []).filter((k) => k.id !== id));
  }

  return (
    <div className="flex-1 max-w-2xl mx-auto w-full px-4 py-8 space-y-8">
      <div>
        <h1 className="text-2xl font-semibold mb-1">LLM API keys</h1>
        <p className="text-sm text-gray-500 mb-4">
          Stored encrypted — only a masked preview is ever shown here, never the real value again.
        </p>

        {keys === null && <p className="text-gray-500">Loading…</p>}
        {keys?.length === 0 && <p className="text-gray-500">No keys added yet.</p>}

        <ul className="divide-y border rounded">
          {keys?.map((k) => (
            <li key={k.id} className="px-4 py-3 flex items-center justify-between">
              <div>
                <span className="font-medium capitalize">{k.provider}</span>{" "}
                <span className="text-sm text-gray-500 font-mono">{k.display_hint}</span>
              </div>
              <button onClick={() => handleDelete(k.id)} className="text-sm text-red-600 underline">
                Delete
              </button>
            </li>
          ))}
        </ul>
      </div>

      <form onSubmit={handleAdd} className="space-y-3">
        <h2 className="text-lg font-medium">Add a key</h2>

        <div className="space-y-1">
          <label htmlFor="provider" className="text-sm font-medium">
            Provider
          </label>
          <select
            id="provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="w-full rounded border px-3 py-2"
          >
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
          </select>
        </div>

        <div className="space-y-1">
          <label htmlFor="apiKey" className="text-sm font-medium">
            API key
          </label>
          <input
            id="apiKey"
            type="password"
            required
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
            className="w-full rounded border px-3 py-2 font-mono"
          />
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="rounded bg-black text-white px-4 py-2 font-medium disabled:opacity-50"
        >
          {submitting ? "Adding…" : "Add key"}
        </button>
      </form>
    </div>
  );
}

export default function ApiKeysRoute() {
  return (
    <RequireAuth>
      <ApiKeysPage />
    </RequireAuth>
  );
}
