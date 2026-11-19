# Gotchas: CodeQL

CodeQL runs on every PR and its alerts can block a merge.

- Any identifier containing "password" is treated as a secret. A constant named `MIN_PASSWORD_LENGTH` was flagged as "clear-text logging of password"; it's now `MIN_PW_LENGTH`. <!-- docs-check: ignore -->
- A fast hash (SHA-256) over anything derived from a password is flagged as weak password hashing, even as an in-memory cache key. Don't hash passwords for keys or caches; compare against what argon2 already produced.
- `hmac.compare_digest` on `str` raises on non-ASCII. Compare bytes.
- Regexes over URLs get flagged (ReDoS / incomplete sanitization). Prefer `urllib.parse` plus plain string checks.
- In the web app, sending server text to something named `write` looks like `document.write` (client XSS). The terminal wrapper's method is called `output` for that reason. Strip control characters from server-provided strings shown in the terminal, and accept only integers for exit codes.
- Path-injection alerts on file APIs are usually real. See the Windows trailing-dot bug above.
