# Troubleshooting

**Start with `athena doctor`.** It checks the host, the container runtime and the server, and says what's missing.

**I can't open the page.** Check the service: `athena service status`. Use the server's address and port 8420. A firewall may block the port. If port 8420 is taken, Athena picks it up from `athena.json`; change it there.

**I forgot my password.** On the server run `athena admin reset-password` (with `sudo` on Linux).

**Apps, Containers or Store are missing, or say the runtime isn't ready.** Athena needs a container runtime. On Linux check Docker is running. On macOS start Colima (`colima start`). On Windows start Docker in WSL2, Podman or Rancher Desktop. Reload the page afterwards.

**An app installed but its page doesn't open.** Open the app's logs. The most common cause is another program using the same port: change the port in the app's settings.

**The Cloud page is missing.** rclone isn't installed or found. Install it with [Packages](packages.md) or your package manager.

**An app is "unsupported" in the store.** It has no image for your CPU. It is hidden unless you click **Show them**.

**Athena won't start after I edited `athena.json`.** The file has an error. `athena config check` shows where. `athena config reset <section>` restores a section.

**The browser warns about the HTTPS certificate.** With the local CA, install and trust the CA on that device. See [Remote access and HTTPS](remote-access-and-https.md).

Still stuck? Use **Send feedback** in the sidebar, or open an issue at <https://github.com/Promethean-Works/athena/issues>.
