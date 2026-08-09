"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { RequireAuth } from "@/components/RequireAuth";
import * as api from "@/lib/api";
import type { Project } from "@/lib/api";
import { ApiError } from "@/lib/api";

function Dashboard() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]));
  }, []);

  async function handleCreate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setCreating(true);
    try {
      const project = await api.createProject(name);
      setProjects((prev) => [...(prev ?? []), project]);
      setName("");
    } catch (err) {
      // Repo creation on Gitea is the slow/likely-to-fail step here, so
      // surface the actual backend detail rather than a generic message.
      setError(err instanceof ApiError ? err.detail : "Failed to create project");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="flex-1 max-w-3xl mx-auto w-full px-4 py-8 space-y-8">
      <div>
        <h1 className="text-2xl font-semibold mb-4">Your projects</h1>

        {projects === null && <p className="text-gray-500">Loading…</p>}
        {projects?.length === 0 && (
          <p className="text-gray-500">No projects yet — create your first one below.</p>
        )}

        <ul className="divide-y border rounded">
          {projects?.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                className="block px-4 py-3 hover:bg-gray-50 flex items-center justify-between"
              >
                <span className="font-medium">{p.name}</span>
                <span className="text-sm text-gray-500">{p.git_repo_path}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>

      <form onSubmit={handleCreate} className="space-y-2">
        <h2 className="text-lg font-medium">New project</h2>
        <div className="flex gap-2">
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My new site"
            className="flex-1 rounded border px-3 py-2"
          />
          <button
            type="submit"
            disabled={creating}
            className="rounded bg-black text-white px-4 py-2 font-medium disabled:opacity-50"
          >
            {creating ? "Creating…" : "Create"}
          </button>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <RequireAuth>
      <Dashboard />
    </RequireAuth>
  );
}
