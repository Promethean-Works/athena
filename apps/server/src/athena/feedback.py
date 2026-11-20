"""Issue links for in-app feedback (docs/specs/feedback.md).

Athena never sends a report itself: it builds a new-issue URL on the right forge, with
the form filled in, and the user's browser opens it. Reports about Athena (and apps from
its built-in catalog) go to Athena's own GitHub issue forms; reports about an app from a
remote catalog go to that catalog's repository when it's on GitHub, Codeberg or GitLab.
"""

import re
from typing import Literal
from urllib.parse import urlencode, urlsplit

Kind = Literal["bug", "change", "feature", "app"]

TEMPLATES: dict[Kind, str] = {
    "bug": "bug_report.yml",
    "change": "change_request.yml",
    "feature": "feature_request.yml",
    "app": "app_report.yml",
}

MAX_LOGS = 4000
"""Characters of logs kept (the end of them): forges refuse URLs much over 8 KB."""

FORGES = ("github.com", "codeberg.org", "gitlab.com")
_NAME = re.compile(r"[\w.-]+")


def repo_of(url: str) -> tuple[str, str] | None:
    """`(host, "owner/repo")` for a GitHub, Codeberg or GitLab repository URL, else None."""
    # urlsplit and fixed-size checks rather than one regex over the whole URL, which is
    # admin input (CodeQL py/polynomial-redos).
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in FORGES:
        return None
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        return None
    owner, repo = segments[0], segments[1].removesuffix(".git")
    if not (_NAME.fullmatch(owner) and _NAME.fullmatch(repo)):
        return None
    return host, f"{owner}/{repo}"


def trim_logs(logs: str) -> tuple[str, bool]:
    """The last `MAX_LOGS` characters, starting on a whole line, and whether it was cut."""
    logs = logs.strip()
    if len(logs) <= MAX_LOGS:
        return logs, False
    tail = logs[-MAX_LOGS:]
    newline = tail.find("\n")
    return (tail[newline + 1 :] if 0 <= newline < 200 else tail), True


def form_url(repo_url: str, kind: Kind, fields: dict[str, str]) -> str:
    """A GitHub issue-form URL with its fields filled from the query string.

    Falls back to a plain title and body when `repo_url` isn't a GitHub repository
    (a fork hosted elsewhere), since only GitHub has issue forms.
    """
    repo = repo_of(repo_url)
    if repo is None or repo[0] != "github.com":
        title = fields.get("title", "")
        body = "\n\n".join(f"**{k}:** {v}" for k, v in fields.items() if k != "title" and v)
        return plain_url(repo_url, title, body)
    query = {"template": TEMPLATES[kind], **{k: v for k, v in fields.items() if v}}
    return f"https://github.com/{repo[1]}/issues/new?{urlencode(query)}"


def plain_url(repo_url: str, title: str, body: str) -> str:
    """A new-issue URL with a title and Markdown body on GitHub, Codeberg or GitLab."""
    repo = repo_of(repo_url)
    if repo is None:
        raise ValueError(f"Not a GitHub, Codeberg or GitLab repository: {repo_url}")
    host, path = repo
    if host == "gitlab.com":
        query = urlencode({"issue[title]": title, "issue[description]": body})
        return f"https://gitlab.com/{path}/-/issues/new?{query}"
    return f"https://{host}/{path}/issues/new?{urlencode({'title': title, 'body': body})}"


def environment_line(os_version: str, arch: str, runtime: str) -> str:
    return f"{os_version} · {arch} · {runtime}"


def app_report_body(
    *,
    app_id: str,
    title: str,
    images: list[str],
    version: str,
    environment: str,
    logs: str,
) -> str:
    """The Markdown body of a report sent to a third-party catalog's repository."""
    lines = [
        f"The app **{title}** (`{app_id}`) doesn't work when installed with "
        "[Athena](https://github.com/tiagozaccaro/athena).",
        "",
        "**What happened:** <!-- what you did, what you expected, what happened -->",
        "",
        f"- Images: {', '.join(f'`{i}`' for i in images) or 'unknown'}",
        f"- Athena: {version}",
        f"- Host: {environment}",
    ]
    if logs:
        lines += ["", "<details><summary>Logs</summary>", "", "```", logs, "```", "", "</details>"]
    return "\n".join(lines)
