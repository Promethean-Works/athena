# Gotchas: Windows portability (CI catches these; your Mac won't)

- Paths written into Linux/macOS files (systemd units, launchd plists, Colima socket paths) must use forward slashes even when generated or tested on Windows. Use `PurePosixPath` or string paths, not `Path`.
- Tests that compare paths must not hard-code `/`. Compare `Path` objects.
- Open text files with `encoding="utf-8"`. Windows defaults to cp1252, which gave a `UnicodeDecodeError` in catalog tests.
- Write test fixtures as bytes (`write_bytes`). Text mode on Windows turns `\n` into `\r\n` and breaks content checks.
- Windows silently strips trailing dots and spaces from names, so `...` resolves to the parent folder. Path containment must check that the final name is unchanged, not only that the parent is inside the root (see `athena/files/paths.py` and design §4.3). This was a real "delete the whole location" bug.
- winget IDs can contain spaces (`ARP\Machine\X64\Mozilla Firefox`), and its truncation ellipsis arrives as `�`.
- Recorded fixtures are stored byte-exact (`apps/server/tests/fixtures/** -text` in `.gitattributes`), so CRLF and spinner `\r` survive.
- In `install.ps1`, a failed native command (e.g. `wsl.exe` with no distro) leaves `$LASTEXITCODE` set, and CI reads the script as failed. Reset it after expected failures.
- PSScriptAnalyzer's unused-parameter rule only looks at the script's top level, so it flags parameters used inside functions (`-Wheel`). Suppress that rule for that parameter with a reason.
- On Windows, `schtasks /End` only kills the venv's `pythonw.exe` launcher. The real interpreter keeps the port and locks the install folder. The installers also stop `pythonw.exe -m athena serve` processes and wait for them.
- PowerShell isn't installed on the maintainer's Mac. The CI run is the first real check of `.ps1` changes.
