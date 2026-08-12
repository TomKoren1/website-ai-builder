from prometheus_client import Counter, Gauge, Histogram

# App-specific metrics called out in overview.md's Phase 5 plan. Process/
# GC/platform metrics are included automatically by prometheus_client's
# default registry — nothing to add for those, they show up in /metrics
# (main.py) for free.

# Labeled by provider ("anthropic"/"openai") and outcome. "error" covers
# both a raised exception from the provider adapter and chat.py's own
# malformed-response case (both mean the call didn't produce something
# usable) — not just an HTTP-level failure reaching the provider.
llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM provider calls",
    ["provider", "outcome"],
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "LLM provider call latency in seconds",
    ["provider"],
)

# In-flight /chat requests — there's no server-side "session" concept to
# count (auth is stateless JWT + a DB-backed refresh token, nothing
# resembling a chat session object), so this measures what's actually
# measurable: how many chat calls are being processed right now.
chat_requests_in_progress = Gauge(
    "chat_requests_in_progress",
    "Number of /chat requests currently being processed",
)

# Flow B's actual "did the site really deploy" signal. Incremented in the
# CI callback (chat.py's deployment_callback), not in push() itself —
# push() only knows the Gitea commit succeeded, not whether the
# subsequent S3 sync did. This is overview.md's "S3 push success/failure
# count."
deployment_callbacks_total = Counter(
    "deployment_callbacks_total",
    "Deployment status callbacks received from CI",
    ["status"],
)
