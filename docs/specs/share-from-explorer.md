# Spec: Share from the file explorer, ask for root, share cloud remotes

**Status:** Approved (2026-11-26), all 3 parts built (#317) · **Milestone:** M6 follow-up (shares) · **Design:** `docs/design/files.md`, `docs/specs/network-shares.md`

## Goal

An admin can share a folder over the network (SMB or NFS) from the file explorer's own "Share…" menu, next to public links, including folders on a cloud remote. When creating the share needs root or administrator rights, Athena asks for them in the dialog instead of showing a dead "needs more permissions" notice.

## Non-goals

- Storing the host password (Keychain, Credential Manager or Athena's database).
- Running the whole panel as root/admin.
- Per-user SMB accounts or Kerberos.
- Installing macFUSE, WinFsp or Samba for the admin (the capability says what's missing).

## Design

### 1. Share from the explorer

The explorer's "Share…" action opens a dialog with two tabs: **Link** (today's public link) and **Network** (SMB or NFS). The Network tab reuses the SMB/NFS forms from `/files/network` (extracted into shared components), prefilled with the current folder. Only folders can be shared this way, and the tab shows the capability's reason when the host can't share.

A share needs a **location** today (one per `locations` row). Sharing a sub-folder of a location is not supported by the shares tables; the tab is offered on a location's root and says so elsewhere. (Open question 1.)

### 2. Asking for root

When a share capability is `needs_privilege`, the create form asks for what the OS needs, per action:

| Host | How |
|---|---|
| Linux | The service already runs as root; nothing to ask. |
| macOS | A password field. The server runs the host command through `sudo -S` with the password on stdin (never argv or env), then discards it. A wrong password returns 403 with a plain message. |
| Windows | No password field. The server starts a one-off elevated PowerShell for the share command; Windows shows its own UAC prompt on the host's screen. Times out after 2 minutes. |

The password is sent in the request body over the session (HTTPS when enabled), kept out of logs, the audit log and error messages, and never stored. The capability stays `needs_privilege` (it describes the service); the create route accepts the elevation and the UI shows the field when the capability says so. The audit log records the action and the user, not the password.

### 3. Cloud remotes

rclone remotes aren't folders, so a share first needs a local mount point:

1. Athena runs `rclone mount <remote>:<path> <data-dir>/mounts/<id>` through the rclone sidecar's config, read-only by default, with a VFS cache.
2. The mount is registered as a hidden location, and the normal SMB/NFS code shares that folder.
3. Mounts start again with Athena (a job at startup) and stop when the share is removed.

Needs FUSE: macFUSE (macOS), `fuse3` (Linux), WinFsp (Windows). A new capability `cloud.mount` (ready when `rclone mount` can run) gates it; the Network tab on a remote explains what's missing. Slow and chatty by nature: the UI says so. Read-write mounts are offered but marked as experimental.

## Parts

One PR for the whole feature (project preference), built in this order:

1. Elevation (macOS `sudo -S`, Windows UAC helper), with the capability and form changes, and tests with a fake `sudo`.
2. The explorer's Network tab and shared forms.
3. Cloud mounts (`cloud.mount`, mount lifecycle, startup restore) and sharing a remote.

## Acceptance checks

- On macOS as a normal user, creating an SMB share from the explorer with the right password works; a wrong password shows an error and changes nothing.
- The password never appears in logs, the audit log, `ps` output or API errors (test).
- A Windows share asks via UAC and works from a non-admin service (CI can't show UAC; manual check).
- A remote folder shared over NFS on Linux mounts from another machine and lists its files.
- Removing the share unmounts the remote; restarting Athena brings active mounts back.
- The sidebar highlights only Network shares on `/files/network/` (fixed in #312).

## Open questions

1. **Sub-folders:** share only a location's root (recommended, no schema change), or let the share store a path inside a location? Recommendation: root only now.
2. **sudo on macOS:** password prompt in the web UI (recommended) vs. asking the admin to run one `sudo athena …` command in a terminal. The first matches "ask for root"; the second never handles a password.
3. **Remote mounts read-only by default?** Recommended yes.
