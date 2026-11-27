"""Search that finds what people mean: query aliases and name matching.

`vscode` shares no substring with Homebrew's `visual-studio-code`, and package managers
only match what a package is called, so we widen the query (aliases, spaces/hyphens) and
rank names ourselves (exact, prefix, substring, abbreviation).
"""

import re

from athena.packages.base import PackageRef

# Normalized query (lowercase letters and digits only) -> extra searches to run. Only
# widely used names that a package's own name doesn't contain.
ALIASES: dict[str, list[str]] = {
    "vscode": ["visual studio code"],
    "code": ["visual studio code"],
    "chrome": ["google chrome"],
    "node": ["nodejs"],
    "nodejs": ["node"],
    "golang": ["go"],
    "postgres": ["postgresql"],
    "k8s": ["kubernetes"],
    "kubectl": ["kubernetes cli"],
    "python": ["python3"],
    "libreoffice": ["libre office"],
    "vlc": ["videolan"],
    "gimp": ["gnu image manipulation program"],
    "obs": ["obs studio"],
    "ytdlp": ["yt-dlp"],
}

_WORD_SPLIT = re.compile(r"[-_.@ /+]+")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def expand_query(query: str) -> list[str]:
    """The query first, then other spellings worth searching, without duplicates."""
    query = query.strip()
    extra = list(ALIASES.get(normalize(query), []))
    if re.search(r"[-_.]", query):
        extra.append(re.sub(r"[-_.]+", " ", query))
    if " " in query:
        extra.append(query.replace(" ", "-"))
    seen = {query.lower()}
    out = [query]
    for q in extra:
        if q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out


def abbreviation_match(query: str, token: str) -> bool:
    """True when the query is made of leading letters of the token's words, in order.

    `vscode` is `v` + `s` + `code` from visual-studio-code. Every word from the first
    contributes (so `vscode` doesn't match `vscode-langservers-extracted`), and trailing
    words may be left out. At least two must contribute, so plain prefixes aren't counted.
    """
    q = normalize(query)
    words = [w for w in _WORD_SPLIT.split(token.lower()) if w]
    if len(q) < 3 or len(words) < 2:
        return False
    words = [re.sub(r"[^a-z0-9]", "", w) for w in words]

    def go(qi: int, wi: int, used: int) -> bool:
        if qi == len(q):
            return used >= 2
        if wi == len(words):
            return False
        word = words[wi]
        for k in range(min(len(word), len(q) - qi), 0, -1):
            if word.startswith(q[qi : qi + k]) and go(qi + k, wi + 1, used + 1):
                return True
        return False

    return go(0, 0, 0)


def match_rank(query: str, name: str, title: str | None = None) -> int:
    """0 exact, 1 abbreviation, 2 prefix, 3 substring, 4 no match (a hit from the manager)."""
    q = normalize(query)
    best = 4
    for text in (name, title or ""):
        n = normalize(text)
        if not n:
            continue
        if n == q:
            return 0
        if abbreviation_match(query, text):
            best = min(best, 1)
        elif n.startswith(q):
            best = min(best, 2)
        elif q in n:
            best = min(best, 3)
    return best


def merge_results(batches: list[list[PackageRef]]) -> list[PackageRef]:
    """Concatenate result lists, keeping the first of each (name, source)."""
    seen: set[tuple[str, str | None]] = set()
    out = []
    for batch in batches:
        for ref in batch:
            key = (ref.name, ref.source)
            if key not in seen:
                seen.add(key)
                out.append(ref)
    return out
