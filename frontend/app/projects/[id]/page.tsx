"use client";

import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { useParams } from "next/navigation";
import { RequireAuth } from "@/components/RequireAuth";
import { PreviewFrame } from "@/components/PreviewFrame";
import * as api from "@/lib/api";
import type { Project } from "@/lib/api";
import { ApiError } from "@/lib/api";

interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

// The assistant's stored message content is the raw JSON it returned
// (see backend WORKFLOW.md) — same shape a live chat response has, so
// history reconstruction and live updates can share this merge logic.
function mergeProposedFiles(
  prev: Record<string, string>,
  proposedFiles: { path: string; content: string }[],
): Record<string, string> {
  const next = { ...prev };
  for (const f of proposedFiles) {
    next[f.path] = f.content;
  }
  return next;
}

function ProjectWorkspace({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [provider, setProvider] = useState("anthropic");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Accumulated across turns, keyed by path. Each chat response only
  // includes files it created/changed (per the backend's system prompt),
  // so this running map — not any single response — is the actual
  // current state of the site. Both the preview and push use this.
  const [files, setFiles] = useState<Record<string, string>>({});

  const [commitMessage, setCommitMessage] = useState("Update site");
  const [pushing, setPushing] = useState(false);
  const [pushResult, setPushResult] = useState<string | null>(null);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch(() => setProject(null));
  }, [projectId]);

  useEffect(() => {
    // Reconstructs both the visible chat log and the accumulated file set
    // from the backend's stored history — without this, every page reload
    // starts from empty state even though the conversation (and the
    // proposed-but-maybe-unpushed files) genuinely still exist server-side.
    api
      .getMessages(projectId)
      .then((history) => {
        const reconstructedTurns: ChatTurn[] = [];
        let reconstructedFiles: Record<string, string> = {};

        for (const m of history) {
          if (m.role === "user") {
            reconstructedTurns.push({ role: "user", content: m.content });
            continue;
          }
          try {
            const parsed = JSON.parse(m.content) as {
              reply: string;
              files: { path: string; content: string }[];
            };
            reconstructedTurns.push({ role: "assistant", content: parsed.reply });
            reconstructedFiles = mergeProposedFiles(reconstructedFiles, parsed.files ?? []);
          } catch {
            // A stored assistant message that isn't valid JSON shouldn't
            // happen (chat.py validates before storing), but don't let a
            // parse failure on one old row break loading the rest.
            reconstructedTurns.push({ role: "assistant", content: m.content });
          }
        }

        setTurns(reconstructedTurns);
        setFiles(reconstructedFiles);
      })
      .catch(() => {});
  }, [projectId]);

  async function submitMessage() {
    if (!message.trim() || sending) return;
    setError(null);
    setSending(true);
    const userMessage = message;
    setMessage("");
    setTurns((prev) => [...prev, { role: "user", content: userMessage }]);
    try {
      const response = await api.chat(projectId, provider, userMessage);
      setTurns((prev) => [...prev, { role: "assistant", content: response.reply }]);
      setFiles((prev) => mergeProposedFiles(prev, response.proposed_files));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Chat request failed");
    } finally {
      setSending(false);
    }
  }

  function handleFormSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    submitMessage();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitMessage();
    }
  }

  async function handlePush() {
    setPushResult(null);
    setPushing(true);
    try {
      const fileList = Object.entries(files).map(([path, content]) => ({ path, content }));
      const deployment = await api.push(projectId, fileList, commitMessage);
      setPushResult(`Pushed commit ${deployment.git_commit_sha.slice(0, 7)} — status: ${deployment.status}`);
    } catch (err) {
      setPushResult(err instanceof ApiError ? `Push failed: ${err.detail}` : "Push failed");
    } finally {
      setPushing(false);
    }
  }

  const hasFiles = Object.keys(files).length > 0;

  return (
    <div className="flex-1 flex min-h-0">
      {/* Chat panel */}
      <div className="w-[420px] shrink-0 border-r flex flex-col min-h-0">
        <div className="px-4 py-3 border-b">
          <h1 className="font-semibold truncate">{project?.name ?? "…"}</h1>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="mt-1 text-sm border rounded px-2 py-1"
          >
            <option value="anthropic">Anthropic</option>
            <option value="openai">OpenAI</option>
          </select>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {turns.length === 0 && (
            <p className="text-sm text-gray-400">
              Describe the site you want — e.g. &ldquo;Create a homepage with a heading that says Hello
              World&rdquo;.
            </p>
          )}
          {turns.map((t, i) => (
            <div key={i} className={t.role === "user" ? "text-right" : ""}>
              <div
                className={`inline-block rounded px-3 py-2 text-sm max-w-[90%] whitespace-pre-wrap ${
                  t.role === "user" ? "bg-black text-white" : "bg-gray-100"
                }`}
              >
                {t.content}
              </div>
            </div>
          ))}
          {sending && <p className="text-sm text-gray-400">Thinking…</p>}
        </div>

        {error && <p className="px-4 pb-2 text-sm text-red-600">{error}</p>}

        <form onSubmit={handleFormSubmit} className="border-t p-3 space-y-2">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={3}
            placeholder="Describe what you want changed… (Enter to send, Shift+Enter for a new line)"
            className="w-full rounded border px-3 py-2 text-sm resize-none"
          />
          <button
            type="submit"
            disabled={sending}
            className="w-full rounded bg-black text-white py-2 text-sm font-medium disabled:opacity-50"
          >
            {sending ? "Thinking…" : "Send"}
          </button>
        </form>
      </div>

      {/* Preview + push panel */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 min-h-0 bg-gray-50">
          <PreviewFrame files={files} />
        </div>

        <div className="border-t p-3 flex items-center gap-2">
          <input
            value={commitMessage}
            onChange={(e) => setCommitMessage(e.target.value)}
            placeholder="Commit message"
            className="flex-1 rounded border px-3 py-2 text-sm"
          />
          <button
            onClick={handlePush}
            disabled={!hasFiles || pushing}
            className="rounded bg-green-700 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {pushing ? "Pushing…" : "Push"}
          </button>
        </div>
        {pushResult && <p className="px-3 pb-3 text-sm text-gray-600">{pushResult}</p>}
      </div>
    </div>
  );
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  return (
    <RequireAuth>
      <ProjectWorkspace projectId={params.id} />
    </RequireAuth>
  );
}
