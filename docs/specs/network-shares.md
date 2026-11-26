# Spec: NFS and SMB shares on every OS that supports them

**Status:** Approved (2026-11-26), parts 1-4 built (#304, #307, #309, #312) · **Milestone:** M6 follow-up (shares) · **Design:** `docs/design/files.md`

## Goal

An admin can publish a file location over SMB (Windows, macOS and Linux clients) or NFS (Linux and macOS clients) from Athena, on whichever host OS can do it, and see the same list and form everywhere. Today SMB creation works only on Linux with Samba, and NFS doesn't exist.

## Non-goals

- NFS on Windows hosts: Windows client editions (Home/Pro) have no NFS server (only Windows Server's "Server for NFS"). The capability reports `unsupported` there.
- Per-user SMB/NFS accounts, Kerberos, LDAP/AD. SMB shares use the host's existing accounts; NFS uses host allow-lists.
- Mounting remote shares on the Athena host (client side).
- Installing Samba or the NFS server for the admin (the capability says what's missing and how to install it, as for Samba today).

## Platforms

| | SMB | NFS |
|---|---|---|
| Linux | Samba: section in `smb.conf`, reload `smbd` (exists). Capability `shares.smb`, ready when `smbd` is found | `nfs-kernel-server` / `nfs-utils`: file `/etc/exports.d/athena.exports`, then `exportfs -ra`. New capability `shares.nfs`, ready when `exportfs` is found and the user is root |
| macOS | Built in: `sharing -a <path> -S <name>` to add, `sharing -r <name>` to remove, `sharing -l` to list | Built in: marked lines in `/etc/exports`, then `nfsd update` (starts nfsd on first export) |
| Windows | Built in: PowerShell `New-SmbShare` / `Remove-SmbShare` / `Get-SmbShare` | `unsupported` (reason in the capability detail) |

Needs root/administrator on every OS. The macOS service is a per-user LaunchAgent today, so on macOS the capability is `needs_privilege` unless Athena runs as root (see open questions). The UI shows each protocol's capability status and reason, and hides the create form when it isn't `ready`.

## Design

- **Server:** replace the `sys.platform` branch in `files/smb.py` with a provider per OS behind one `ShareProvider` interface (`files/sharing/base.py`, `samba.py`, `macos.py`, `windows.py`, `nfs_linux.py`, `nfs_macos.py`), chosen from the capability manifest, per the "never branch on `sys.platform` in a router" rule. `files/smb.py` keeps the public API and tracking. Add `detect_nfs` in `platform/detect.py` and update `detect_smb` for macOS and Windows.
  - Routes: keep `/api/shares/smb`; add `GET/POST /api/shares/nfs` and `DELETE /api/shares/nfs/{id}` (`listNfsShares`, `createNfsShare`, `deleteNfsShare`). NFS create takes `locationId`, `readOnly`, and `clients` (CIDR/host list, default: the host's LAN subnet is **not** assumed; an empty list is refused). `pnpm gen:api` after.
  - Model: `nfs_shares` table (Alembic migration), mirroring `smb_shares`.
  - Config edits are rewritten atomically (temp file + replace), only touch lines/sections Athena owns (marker comments for exports), and validate every value (share name regex, client entries parsed with `ipaddress`/hostname regex, path comes from a stored location, never from the request). Commands use argument lists.
  - Audit `nfs.share.create|remove` (SMB already audits `smb.share.*`).
  - On startup, drop tracking rows whose config entry vanished? No: show them as "missing on host" with a remove button, so nothing deletes silently.
- **Web:** `/files/smb` becomes a "Network shares" page with SMB and NFS tabs (the shadcn tabs already in `packages/ui`), reusing `smb-shares-view.tsx` as a generic list. Each tab shows capability state, the connection string to copy (`\\host\name`, `smb://host/name`, `host:/path`), and the NFS clients field. Sidebar entry gated on either capability.
- **Assistant / MCP:** none in part 1. Later: `create_network_share` in `actions.py` (approval card).
- **Security:** admins only, CSRF as for all writes. Guest SMB and wide-open NFS (`*`) need an explicit confirm in the form and a warning on the card. NFS has no authentication beyond client address, so the form says so.
- **Dependencies:** none new (OS tools only).

## Parts

1. **Provider refactor + Linux NFS.** Interface, `nfs_shares` migration, `shares.nfs` capability, NFS routes and tests with a temp exports file; audit entries for SMB. Verified: unit tests, a Lima VM with `nfs-kernel-server` and a real mount from the host (`athena-host-test`).
2. **macOS SMB and NFS.** `sharing` and `nfsd` providers, with fixtures recorded from a real Mac. Verified on this Mac (as root).
3. **Windows SMB.** `New-SmbShare` provider. Verified in CI on Windows (create/list/remove with a temp folder) and by hand.
4. **UI.** Tabs page, capability states, connection strings, confirms. Verified with `athena-ui-verify` (fake providers in the browser check, since this changes the host).

## Acceptance checks

- Unit: name/client validation, exports and `smb.conf` edits keep unrelated lines, removing a share removes only Athena's entry, duplicate names, unsupported OS returns 501 with the capability's reason.
- Real: Linux (Lima) SMB and NFS shares mountable from the host; macOS `sharing -l` and `showmount -e` show the share; Windows `Get-SmbShare` in CI.
- Failure cases: tool missing, not root, config file unwritable, reload fails (the entry is rolled back, not tracked).
- Browser: phone width, dark mode, console and network clean.

## Open questions

- **Privilege on macOS.** The service runs as the user, but `sharing` and `/etc/exports` need root. Options: run Athena as a LaunchDaemon, or call `sudo`/an admin prompt. Recommendation: mark macOS `needs_privilege` unless already root, ship Linux and Windows first, and decide the macOS privilege model in its own spec before part 2.
- **Windows service account.** Same question: `New-SmbShare` needs an elevated service. Recommendation: check what `athena service install` uses today and gate the capability on a real elevation check.
- **NFS default clients.** Recommendation: no default, the admin must enter one (a subnet or host).
- **NFS v4 only vs v3.** Recommendation: don't pin; write plain exports and leave version to the host.
- **Existing SMB code uses `sys.platform` in the module and a `_reload_smbd` that ignores failures.** Recommendation: fix both in part 1 (roll back on a failed reload).
