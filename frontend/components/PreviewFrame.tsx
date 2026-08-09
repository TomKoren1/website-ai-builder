"use client";

import { useEffect, useMemo, useState } from "react";
import { buildPreviewHtml } from "@/lib/preview";

export function PreviewFrame({ files }: { files: Record<string, string> }) {
  const [currentPath, setCurrentPath] = useState<string | null>(null);

  // `files` gets a new object identity on every chat turn (see the project
  // page's setFiles), so this fires exactly when new content arrives —
  // resets the preview to the entry page rather than leaving it stranded
  // on a subpage that may no longer reflect the latest turn.
  useEffect(() => {
    setCurrentPath(null);
  }, [files]);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.data?.type !== "preview-navigate") return;
      const path = String(event.data.path)
        .replace(/^\.\//, "")
        .replace(/^\//, "");
      if (files[path]) {
        setCurrentPath(path);
      }
      // Silently ignored otherwise — a link to a page the AI didn't
      // actually create shouldn't crash the preview, just do nothing.
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [files]);

  const html = useMemo(() => buildPreviewHtml(files, currentPath ?? undefined), [files, currentPath]);

  if (!html) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400 text-sm">
        No index.html yet — ask the AI to create one.
      </div>
    );
  }

  return (
    // sandbox="allow-scripts" only (no allow-same-origin) — this is
    // AI-generated content the user hasn't reviewed yet. It can run its
    // own JS and postMessage out (both allowed under this sandbox), but
    // can't reach cookies, storage, or anything else on our actual origin.
    <iframe title="Site preview" sandbox="allow-scripts" srcDoc={html} className="w-full h-full border-0" />
  );
}
