"""GitHub REST API client, search query construction, and error handling.

Handles authentication, pagination, rate limits, transient network retries,
and issue / repository data retrieval for RuneCLI.
"""

import os
import re
import sys
from collections.abc import Generator, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from rune import theme
from rune.models import IssueRef, RepoMeta
from rune.ui import get_console, redact, sanitize, truncate

# GitHub username format: alphanumeric start, up to 38 alphanumeric or hyphen chars
SAGE_REGEX = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


class GitHubError(Exception):
    """Base exception for GitHub API errors. All messages are redacted."""

    def __init__(self, message: str = ""):
        super().__init__(redact(str(message)))


class GitHubAuthError(GitHubError):
    """Raised when GitHub returns 401 Unauthorized."""


class ParsedResetTime(datetime):
    """Subclass of datetime supporting int timestamp comparison and conversion."""

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return abs(self.timestamp() - float(other)) < 1.0
        return super().__eq__(other)

    def __int__(self) -> int:
        return int(self.timestamp())


class GitHubRateLimitError(GitHubError):
    """Raised when GitHub returns 403 or 429 rate limit errors."""

    def __init__(self, message: str = "", reset_time: ParsedResetTime | None = None):
        super().__init__(message)
        self.reset_time = reset_time


class GitHubNotFoundError(GitHubError):
    """Raised when GitHub returns 404 Not Found."""


def parse_reset_time(response: httpx.Response) -> ParsedResetTime | None:
    """Parse rate limit reset time from X-RateLimit-Reset epoch or Retry-After seconds."""
    # 1. X-RateLimit-Reset (epoch timestamp)
    reset_val = response.headers.get("x-ratelimit-reset")
    if reset_val:
        try:
            epoch = float(reset_val)
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
            return ParsedResetTime(
                dt.year,
                dt.month,
                dt.day,
                dt.hour,
                dt.minute,
                dt.second,
                dt.microsecond,
                tzinfo=dt.tzinfo,
            )
        except (ValueError, TypeError, OSError):
            pass

    # 2. Retry-After (seconds)
    retry_val = response.headers.get("retry-after")
    if retry_val:
        try:
            seconds = float(retry_val)
            dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            return ParsedResetTime(
                dt.year,
                dt.month,
                dt.day,
                dt.hour,
                dt.minute,
                dt.second,
                dt.microsecond,
                tzinfo=dt.tzinfo,
            )
        except (ValueError, TypeError):
            pass

    return None


def extract_keywords(text: str) -> list[str]:
    """Extract up to 8 alphanumeric words of length >= 3 from text."""
    if not text:
        return []
    words = re.findall(r"[A-Za-z0-9]+", text)
    valid_words = [w for w in words if len(w) >= 3]
    return valid_words[:8]


def validate_sage(sage: str | None) -> bool:
    """Validate GitHub sage username against ^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$."""
    if not sage:
        return False
    return bool(SAGE_REGEX.match(sage.strip()))


def build_search_query(
    keywords: list[str],
    unassigned: bool = True,
    sage: str | None = None,
) -> str:
    """Compose the GitHub search query string.

    Base: is:issue is:open is:public archived:false in:title,body
    Optional: no:assignee (when unassigned=True)
    Optional: user:<sage> (when sage is provided and valid)
    Keywords: alphanumeric tokens of length >= 3, max 8, colon/quotes stripped.
    Query is capped at 256 characters.
    """
    parts = ["is:issue", "is:open", "is:public", "archived:false", "in:title,body"]

    if unassigned:
        parts.append("no:assignee")

    if sage and sage.strip():
        parts.append(f"user:{sage.strip()}")

    # Sanitize keywords: strip quotes and colons to prevent qualifier injection
    safe_keywords: list[str] = []
    for kw in keywords:
        clean = re.sub(r'[:"\'\s]', "", kw)
        if len(clean) >= 3 and clean.isalnum():
            safe_keywords.append(clean)

    if safe_keywords:
        parts.append(" ".join(safe_keywords[:8]))

    q = " ".join(parts)
    if len(q) > 256:
        q = q[:256]
    return q


def parse_issue_item(item: dict[str, Any], unassigned: bool = True) -> IssueRef | None:
    """Parse raw GitHub search issue dict into IssueRef.

    Returns None if missing required fields, if item represents a PR,
    or if unassigned=True and an assignee is present.
    """
    if "pull_request" in item:
        return None

    for req in ("number", "title", "html_url", "repository_url"):
        if req not in item or item[req] is None:
            return None

    repo_url = str(item["repository_url"])
    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        return None
    base_repo = f"{parts[-2]}/{parts[-1]}"

    assignee_logins: list[str] = []
    assignees = item.get("assignees")
    if isinstance(assignees, list):
        for a in assignees:
            if isinstance(a, dict) and "login" in a and a["login"]:
                assignee_logins.append(str(a["login"]))
    if not assignee_logins:
        assignee = item.get("assignee")
        if isinstance(assignee, dict) and "login" in assignee and assignee["login"]:
            assignee_logins.append(str(assignee["login"]))

    if unassigned and assignee_logins:
        return None

    body = item.get("body")
    if body is None:
        body = ""

    return IssueRef(
        number=int(item["number"]),
        title=str(item["title"]),
        body=str(body),
        url=str(item["html_url"]),
        base_repo=base_repo,
        assignee_logins=assignee_logins,
    )


def format_issue_label(issue: IssueRef, max_width: int = 80) -> str:
    """Format sanitized and truncated issue choice label: 'owner/repo #n title'."""
    raw = f"{issue.base_repo} #{issue.number} {issue.title}"
    return truncate(sanitize(raw), max_width)


def select_single_issue(selected: Sequence[IssueRef] | IssueRef | None) -> IssueRef:
    """Ensure exactly one issue was selected. Rejects 0 or >1 with ValueError."""
    if selected is None:
        raise ValueError("No issue selected. Exactly one issue must be selected.")
    if isinstance(selected, IssueRef):
        return selected
    if len(selected) != 1:
        raise ValueError(
            f"Exactly one issue must be selected, but {len(selected)} were provided."
        )
    return selected[0]


# Alias for selection helper
select_issue = select_single_issue


class GitHubClient:
    """Client for the GitHub REST API."""

    def __init__(
        self,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if token is None:
            token = os.environ.get("GITHUB_TOKEN")
        if not token or not str(token).strip():
            get_console().print(redact(theme.missing_token))
            sys.exit(1)

        self._token = token.strip()
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "rune-cli",
        }
        self._client = httpx.Client(
            base_url="https://api.github.com",
            timeout=15.0,
            headers=headers,
            transport=transport,
        )

    def __repr__(self) -> str:
        return "<GitHubClient>"

    def __str__(self) -> str:
        return "<GitHubClient>"

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Execute HTTP request with at most one retry on transient transport errors.

        HTTP error statuses are never retried.
        """
        response: httpx.Response | None = None
        last_exc: Exception | None = None

        for attempt in range(2):
            try:
                response = self._client.request(method, url, **kwargs)
                break
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt == 1:
                    raise GitHubError(redact(f"Network error after retry: {exc}")) from exc
                continue

        if response is None:
            raise GitHubError(redact(f"Network error: {last_exc}"))

        if response.status_code == 401:
            raise GitHubAuthError(redact(theme.auth_failed))

        if response.status_code in (403, 429):
            reset_time = parse_reset_time(response)
            if reset_time:
                local_time = reset_time.astimezone().strftime("%H:%M:%S")
                msg = theme.rate_limit.format(time=local_time)
            else:
                msg = "The gods are not listening. Rate limit exceeded."
            raise GitHubRateLimitError(redact(msg), reset_time=reset_time)

        if response.status_code == 404:
            raise GitHubNotFoundError(redact(f"Resource not found (404): {url}"))

        if response.is_error:
            raise GitHubError(
                redact(f"GitHub API error {response.status_code}: {response.text}")
            )

        return response

    def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Send a GET request."""
        return self.request("GET", url, params=params)

    def paginate(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        max_pages: int = 10,
    ) -> list[Any]:
        """Follow response.links['next'] up to max_pages."""
        items: list[Any] = []
        current_url: str | None = url
        current_params: dict[str, Any] | None = params
        pages = 0

        while current_url and pages < max_pages:
            resp = self.get(current_url, params=current_params)
            pages += 1
            data = resp.json()
            if isinstance(data, list):
                items.extend(data)
            elif isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
                items.extend(data["items"])
            else:
                items.append(data)

            next_link = resp.links.get("next")
            if next_link and "url" in next_link:
                current_url = next_link["url"]
                current_params = None
            else:
                break

        return items

    def paginate_responses(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        max_pages: int = 10,
    ) -> Generator[httpx.Response, None, None]:
        """Yield response objects following response.links['next'] up to max_pages."""
        current_url: str | None = url
        current_params: dict[str, Any] | None = params
        pages = 0

        while current_url and pages < max_pages:
            resp = self.get(current_url, params=current_params)
            pages += 1
            yield resp
            next_link = resp.links.get("next")
            if next_link and "url" in next_link:
                current_url = next_link["url"]
                current_params = None
            else:
                break

    def get_authenticated_login(self) -> str:
        """Retrieve the login username of the authenticated token via GET /user."""
        resp = self.get("/user")
        data = resp.json()
        login = data.get("login")
        if not login:
            raise GitHubError("Failed to retrieve authenticated login from GitHub.")
        return str(login)

    def search_issues(
        self,
        q: str,
        per_page: int = 10,
        unassigned: bool = True,
    ) -> list[IssueRef]:
        """Execute a single issue search request via GET /search/issues.

        Never polls, sleeps, or repeats searching.
        """
        resp = self.get("/search/issues", params={"q": q, "per_page": per_page})
        data = resp.json()
        raw_items = data.get("items", [])
        results: list[IssueRef] = []
        for raw in raw_items:
            ref = parse_issue_item(raw, unassigned=unassigned)
            if ref is not None:
                results.append(ref)
        return results

    def get_repo(self, base_repo: str) -> RepoMeta:
        """Fetch repository metadata and permissions via GET /repos/{base_repo}."""
        resp = self.get(f"/repos/{base_repo}")
        data = resp.json()

        permissions = data.get("permissions")
        push = False
        if isinstance(permissions, dict):
            push = bool(permissions.get("push") is True)

        archived = bool(data.get("archived", False))
        allow_forking = bool(data.get("allow_forking", True))
        html_url = data.get("html_url", f"https://github.com/{base_repo}")
        default_branch = data.get("default_branch", "main")

        return RepoMeta(
            base_repo=base_repo,
            base_repo_url=html_url,
            default_branch=default_branch,
            archived=archived,
            allow_forking=allow_forking,
            push=push,
        )
