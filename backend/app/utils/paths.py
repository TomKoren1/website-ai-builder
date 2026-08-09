import posixpath
import re

# Allowlist, not blocklist: only ASCII letters/digits/underscore/dot/hyphen
# per path segment. This is deliberately stricter than "block .. and leading
# slash" — that approach only catches literal ".." substrings, and misses
# backslashes (a separator on other platforms), percent-encoded traversal
# sequences ("%2e%2e%2f"), and characters like "#"/"?"/"&" that mean
# something special once the path is used to build a URL (see
# gitea_client.py, which interpolates this path directly into a Gitea API
# request — an unencoded "#" or "?" there changes what request is actually
# sent, regardless of whether it also contains "..").
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


def is_safe_project_path(path: str) -> bool:
    """True if `path` is a plain relative path that stays inside the project
    directory and contains nothing that could be reinterpreted by a
    downstream URL/filesystem layer.

    The LLM returns file paths as plain strings in its response — untrusted
    input. Without this check, a returned path like "../../etc/passwd", an
    absolute path, or a URL-meaningful character could let generated
    content write outside the project's own file tree or manipulate the
    Gitea API request built from it.
    """
    if not path or "\\" in path or path.startswith("/"):
        return False

    normalized = posixpath.normpath(path)
    if normalized.startswith("..") or normalized == "..":
        return False

    return all(_SAFE_SEGMENT.match(segment) for segment in normalized.split("/"))
