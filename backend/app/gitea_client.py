import base64
from urllib.parse import quote

import httpx

from app.config import get_settings

settings = get_settings()

# All project repos live under this fixed Gitea organization rather than
# per-user Gitea accounts — our own users aren't Gitea users, so there's no
# natural "owner" otherwise. Create this org once via the Gitea UI/API
# before the first project is created (see PHASE2-RUNBOOK.md).
ORG = "projects"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.gitea_url,
        headers={"Authorization": f"token {settings.gitea_admin_token}"},
        timeout=10.0,
    )


async def create_repo(name: str) -> str:
    """Creates a private repo under ORG. Returns its "owner/name" path."""
    async with _client() as client:
        response = await client.post(
            f"/api/v1/orgs/{ORG}/repos",
            json={"name": name, "private": True, "auto_init": True},
        )
        response.raise_for_status()
    return f"{ORG}/{name}"


async def create_or_update_file(repo_path: str, file_path: str, content: str, message: str) -> str:
    """repo_path is "owner/name" (e.g. what create_repo returned). Returns the new commit sha."""
    owner, repo = repo_path.split("/", 1)
    encoded = base64.b64encode(content.encode()).decode()
    # Encode each segment separately (not the whole path at once) so the
    # "/" separators stay intact while everything else — including any
    # character is_safe_project_path didn't anticipate — gets escaped
    # before it ever becomes part of a URL. Defense in depth: this holds
    # even if the caller forgot to validate the path at all.
    url_path = "/".join(quote(segment, safe="") for segment in file_path.split("/"))

    async with _client() as client:
        # Gitea requires the file's current sha on update but not on create —
        # check existence first rather than branching on a failed PUT.
        existing = await client.get(f"/api/v1/repos/{owner}/{repo}/contents/{url_path}")
        body = {"content": encoded, "message": message, "branch": "main"}
        if existing.status_code == 200:
            body["sha"] = existing.json()["sha"]
            response = await client.put(f"/api/v1/repos/{owner}/{repo}/contents/{url_path}", json=body)
        else:
            response = await client.post(f"/api/v1/repos/{owner}/{repo}/contents/{url_path}", json=body)
        response.raise_for_status()
        return response.json()["commit"]["sha"]


async def commit_files(repo_path: str, files: dict[str, str], message: str) -> str:
    """Writes each path->content pair as its own commit and returns the last
    commit's sha. Simple and correct for a handful of static-site files;
    would need Gitea's git-tree API instead of per-file PUT/POST if a
    project ever has hundreds of files in one push."""
    sha = ""
    for file_path, content in files.items():
        sha = await create_or_update_file(repo_path, file_path, content, message)
    return sha


async def dispatch_workflow(repo_path: str, workflow_file: str, inputs: dict[str, str]) -> None:
    """Triggers a `workflow_dispatch`-triggered workflow (see
    .gitea/workflows/deploy.yml, seeded into every project repo at creation
    in projects.py) with the given inputs. Deliberately used instead of a
    plain `on: push` trigger: it's the only way to hand the workflow a
    per-deployment one-time callback token without ever writing that token
    into the repo/commit itself (see chat.py's push() for where the token
    is generated)."""
    owner, repo = repo_path.split("/", 1)
    async with _client() as client:
        response = await client.post(
            f"/api/v1/repos/{owner}/{repo}/actions/workflows/{workflow_file}/dispatches",
            json={"ref": "main", "inputs": inputs},
        )
        response.raise_for_status()
