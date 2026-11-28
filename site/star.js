// Fills the star count on every "Star on GitHub" button (a[data-star]) from the public GitHub API.
// The link works without it; if the request fails or is rate-limited the count stays hidden.
(function () {
  var KEY = "athena-stars"
  function show(n) {
    var text = n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k" : String(n)
    document.querySelectorAll("[data-star] .count").forEach(function (el) {
      el.textContent = text
      el.hidden = false
    })
  }
  try {
    var c = JSON.parse(sessionStorage.getItem(KEY) || "null")
    if (c && Date.now() - c.t < 600000) return show(c.n)
  } catch (e) {}
  fetch("https://api.github.com/repos/Promethean-Works/athena", { headers: { Accept: "application/vnd.github+json" } })
    .then(function (r) { return r.ok ? r.json() : Promise.reject() })
    .then(function (d) {
      if (typeof d.stargazers_count !== "number") return
      try { sessionStorage.setItem(KEY, JSON.stringify({ n: d.stargazers_count, t: Date.now() })) } catch (e) {}
      show(d.stargazers_count)
    })
    .catch(function () {})
})()
