// Adds a copy-to-clipboard icon button to every install command (.cmd) and code block (pre).
(function () {
  var COPY = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
  var CHECK = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>'
  document.querySelectorAll("pre, .cmd").forEach(function (host) {
    var code = host.querySelector("code")
    if (!code) return
    var b = document.createElement("button")
    b.type = "button"
    b.className = "copy"
    b.setAttribute("aria-label", "Copy to clipboard")
    b.title = "Copy"
    b.innerHTML = COPY
    b.addEventListener("click", function () {
      navigator.clipboard.writeText(code.innerText.trim()).then(function () {
        b.innerHTML = CHECK
        b.classList.add("done")
        b.title = "Copied"
        setTimeout(function () { b.innerHTML = COPY; b.classList.remove("done"); b.title = "Copy" }, 1600)
      })
    })
    host.appendChild(b)
  })
})()
