// A sandboxed srcDoc iframe has no server behind it, so it can't fetch
// sibling files like css/style.css the way a real deployed site can — the
// AI's generated <link href="css/style.css"> would just 404 silently
// inside the sandbox. This inlines any referenced local CSS/JS directly
// into the HTML before it's ever handed to the iframe.
//
// It also can't navigate to a second page (a link to yuval.html has
// nothing to load — there's no server, just one HTML string). The
// injected script at the bottom intercepts local link clicks and asks
// the parent (via postMessage — allowed even under a strict sandbox,
// unlike direct DOM access) to swap in that page instead. See
// components/PreviewFrame.tsx for the receiving end.
//
// Regex-based, not a full HTML parser — good enough for the plain,
// AI-generated static HTML this app deals with, not a general solution.
export function buildPreviewHtml(files: Record<string, string>, entryPath?: string): string | null {
  const resolvedEntry =
    entryPath && files[entryPath]
      ? entryPath
      : files["index.html"]
        ? "index.html"
        : Object.keys(files).find((p) => p.endsWith(".html"));
  if (!resolvedEntry) return null;

  let html = files[resolvedEntry];
  const normalize = (p: string) => p.replace(/^\.\//, "");
  const lookup = (raw: string): string | undefined => files[normalize(raw)];

  // <link rel="stylesheet" href="..."> — two passes since attribute order
  // ("rel" before "href" or vice versa) isn't something the model is
  // guaranteed to be consistent about.
  const linkPatterns = [
    /<link\b[^>]*\brel=["']stylesheet["'][^>]*\bhref=["']([^"']+)["'][^>]*>/gi,
    /<link\b[^>]*\bhref=["']([^"']+)["'][^>]*\brel=["']stylesheet["'][^>]*>/gi,
  ];
  for (const pattern of linkPatterns) {
    html = html.replace(pattern, (match, href) => {
      const css = lookup(href);
      return css ? `<style>\n${css}\n</style>` : match;
    });
  }

  // <script src="...">...</script>
  html = html.replace(/<script\b([^>]*)\bsrc=["']([^"']+)["']([^>]*)><\/script>/gi, (match, before, src, after) => {
    const js = lookup(src);
    return js ? `<script${before}${after}>\n${js}\n</script>` : match;
  });

  // Intercept local link clicks -> ask the parent to switch pages.
  // Skips anything with a URI scheme (http:, mailto:, etc.), protocol-
  // relative URLs, and same-page hash links (#foo) — those should behave
  // like normal links, not trigger a page swap.
  html += `
<script>
(function () {
  document.addEventListener("click", function (e) {
    var a = e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href");
    if (!href || /^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("//") || href.startsWith("#")) {
      return;
    }
    e.preventDefault();
    window.parent.postMessage({ type: "preview-navigate", path: href }, "*");
  });
})();
</script>`;

  return html;
}
