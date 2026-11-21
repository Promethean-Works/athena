---
name: athena-host-test
description: Tests Athena on a real Linux, macOS or Windows host instead of only in unit tests - the one-line installers, the system service, capability detection and package managers (apt, dnf, pacman, zypper, apk) - using a throwaway Lima VM locally or the E2E GitHub workflow. Use when a change touches scripts/install.sh, scripts/install.ps1, `athena service`, platform detection or a package manager, or when docs/STATUS.md lists something as "not verified on a real host".
---

# Test on a real host

Unit tests and fixtures prove the parsers. This proves the real installer, service and tools work. Pick the route:

| Need | Route |
|---|---|
| Linux with systemd (Ubuntu, Fedora, Arch, openSUSE, Alpine) | **Lima VM** on the developer's Mac (below) |
| Windows, Ubuntu or macOS runners, scripted | **E2E workflow** on GitHub (below) |
| Windows desktop features (Docker in WSL, Explorer WebDAV mount) | Not possible from an agent. List it in STATUS as a manual check for the maintainer |

Docker containers are **not** a substitute: they have no systemd, so the service install can't be tested in them. They're fine for recording package-manager fixtures (see `apps/server/tests/fixtures/packages/README.md`).

## 1. Build what you're testing

Test the commit, not the last release:

```bash
pnpm install --frozen-lockfile
scripts/build-wheel.sh               # -> dist/athena_server-<v>-py3-none-any.whl (UI + catalog bundled)
```

## 2a. Lima VM (local Linux)

```bash
limactl list                                         # reuse an existing athena-* VM if there is one
limactl start --name athena-ubuntu --tty=false --cpus 4 --memory 4 template://ubuntu-24.04
#   other distros: template://fedora (dnf), template://archlinux (pacman),
#   template://opensuse (zypper), template://alpine (apk; OpenRC, not systemd)
```

- Lima mounts the Mac's home folder read-only in the VM at the same path, so the repo and `dist/` are visible as they are.
- Lima forwards the VM's listening ports to the Mac's `localhost`. The VM's Athena on 8420 shows up as the Mac's `localhost:8420` and can clash with a local Athena. Check `lsof -nP -iTCP:8420 -sTCP:LISTEN` first.

Install and check:

```bash
WHEEL=$(ls "$PWD"/dist/athena_server-*.whl)
limactl shell athena-ubuntu -- sudo bash "$PWD/scripts/install.sh" --wheel "$WHEEL"
limactl shell athena-ubuntu -- bash -c 'systemctl is-active athena; sudo athena service status; curl -s localhost:8420/api/health'
```

Browser smoke test (from the Mac, through the forwarded port; the data dir must be fresh):

```bash
uv run --with playwright==1.65.2 playwright install chromium    # once
uv run scripts/e2e/smoke.py --url http://localhost:8420 --out e2e-out --expect terminal.host --expect containers
```

API checks inside the VM (package install as a job, then confirm with the real tool):

```bash
limactl shell athena-ubuntu -- bash -s <<'EOF'
set -e; cd /tmp; B=http://localhost:8420
curl -s -c jar -o login.json -H 'content-type: application/json' \
  -d '{"username":"admin","password":"e2e-test-pass-1234"}' $B/api/auth/login
CSRF=$(jq -r .csrf_token login.json)          # sudo apt-get install -y jq, if missing
curl -s -b jar -o caps.json $B/api/system/capabilities && jq '.' caps.json | head -40
curl -s -b jar -X POST -H "X-CSRF-Token: $CSRF" -H 'content-type: application/json' \
  -d '{"name":"sl"}' $B/api/packages/apt/install        # returns a job; poll GET $B/api/jobs/<id>
EOF
limactl shell athena-ubuntu -- dpkg -s sl | head -3     # the side effect, checked outside Athena
```

HTTPS: self-signed, across a restart, then `athena https off`. The server's venv already has httpx and cryptography, so the VM needs no uv:

```bash
P=/opt/athena/tools/athena-server/bin/python; S="$PWD/scripts/e2e/https_check.py"
limactl shell athena-ubuntu -- bash -c "cd /tmp && $P $S on --out /tmp/hout \
  && sudo systemctl restart athena && $P $S check --out /tmp/hout \
  && sudo athena https off --data-dir /var/lib/athena && sudo systemctl restart athena \
  && $P $S off --out /tmp/hout"
```

Let's Encrypt HTTP-01 with real port-80 validation (CI's Pebble skips validation). Pebble validates by connecting to the domain on port 80, and `pebble-challtestsrv` answers every DNS query with the VM's address. Use port 14010, not 14000: Lima forwards VM ports to the Mac, where another Pebble may already hold 14000. The flag is `-dnsserver`; challtestsrv 2.10.3 has no `-dns01` and exits at once.

```bash
limactl shell athena-ubuntu -- bash -s <<'SH'
set -e; mkdir -p /tmp/peb && cd /tmp/peb
IP=$(ip -4 -br addr show eth0 | awk '{print $3}' | cut -d/ -f1)
sudo docker create --name athena-test-pebcfg ghcr.io/letsencrypt/pebble:2.10.3 >/dev/null
sudo docker cp athena-test-pebcfg:/test ./test; sudo docker rm athena-test-pebcfg >/dev/null
jq '.pebble.httpPort=80 | .pebble.listenAddress="0.0.0.0:14010" | .pebble.managementListenAddress="127.0.0.1:15010"' \
  test/config/pebble-config.json > port80.json
sudo docker run -d --name athena-test-challtestsrv --network host ghcr.io/letsencrypt/pebble-challtestsrv:2.10.3 \
  -defaultIPv4 "$IP" -dnsserver 127.0.0.1:8053 -http01 "" -https01 "" -tlsalpn01 "" -doh "" -management 127.0.0.1:8055
sudo docker run -d --name athena-test-pebble --network host -e PEBBLE_VA_NOSLEEP=1 -e PEBBLE_WFE_NONCEREJECT=0 \
  -v /tmp/peb/port80.json:/port80.json:ro ghcr.io/letsencrypt/pebble:2.10.3 -config /port80.json -dnsserver 127.0.0.1:8053
sudo cp test/certs/pebble.minica.pem /var/lib/athena/
sudo mkdir -p /etc/systemd/system/athena.service.d
printf '[Service]\nEnvironment=ATHENA_ACME_DIRECTORY=https://localhost:14010/dir\nEnvironment=ATHENA_ACME_CA_CERTIFICATES=/var/lib/athena/pebble.minica.pem\n' \
  | sudo tee /etc/systemd/system/athena.service.d/athena-test-pebble.conf
sudo systemctl daemon-reload && sudo systemctl restart athena
SH
```

Then sign in, `POST /api/https/certificate` with `{"domains":["nas.athena-test.example.com"],"email":"admin@athena-test.example.com","challenge":"http"}`, poll `GET /api/jobs/<id>` (its `lines` hold lego's output) and `PUT /api/https` with mode `letsencrypt`. To check the refusal when port 80 is taken, hold it first: `sudo systemd-run --unit athena-test-port80 python3 -m http.server 80`. Afterwards remove the two containers, the drop-in and `/tmp/peb`.

Uninstall check, then clean up:

```bash
limactl shell athena-ubuntu -- sudo bash "$PWD/scripts/install.sh" --uninstall --purge
limactl shell athena-ubuntu -- bash -c 'ls /etc/systemd/system/athena.service /var/lib/athena /opt/athena /usr/local/bin/athena 2>&1; curl -s -m 3 localhost:8420/api/health || echo "port closed"'
limactl stop athena-ubuntu && limactl delete athena-ubuntu     # only VMs you created
```

The installer flags are `--version`, `--wheel <path|url>`, `--no-runtime`, `--dry-run`, `--uninstall` and `--purge`. On Windows, `install.ps1` takes `-Version`, `-Wheel`, `-DryRun`, `-Uninstall` and `-Purge`.

## 2b. E2E workflow (GitHub runners: Ubuntu, macOS, Windows Server)

```bash
gh workflow run E2E --ref <branch>                  # also runs by itself on installer/service changes
gh run list --workflow E2E --branch <branch> --limit 1
gh run watch <run-id>; gh run view <run-id> --log-failed | tail -80
gh run download <run-id> -D e2e-artifacts            # screenshots, capabilities.json, logs
```

Limits: hosted runners can't run Colima (macOS) or WSL2 (Windows), so containers are only checked end to end on Ubuntu.

## 3. Record the result

- Put what you verified, and on which OS and version, in `docs/STATUS.md`, and take the item off "Not yet verified".
- A real-host bug that unit tests missed usually deserves a test plus a bullet in `docs/agents/gotchas/`. One example: Windows `schtasks /End` left the real interpreter running.
- Delete `e2e-out/` and `e2e-artifacts/`; don't commit screenshots.
