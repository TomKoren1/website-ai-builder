import posixpath


def is_safe_project_path(path: str) -> bool:
    """True if `path` stays inside the project directory once normalized.

    The LLM returns file paths as plain strings in its response — untrusted
    input. Without this check, a returned path like "../../etc/passwd" or
    an absolute path would let generated content write outside the
    project's own file tree.
    """
    if not path or path.startswith("/") or path.startswith("\\"):
        return False

    normalized = posixpath.normpath(path)
    return not normalized.startswith("..") and normalized != ".."
