// Automatic screenshot slider: advances every 4.5 s, pauses on hover, focus and when the
// tab is hidden, and stays still when the visitor prefers reduced motion.
(function () {
  var root = document.querySelector(".slider")
  if (!root) return
  var track = root.querySelector(".track")
  var slides = root.querySelectorAll(".slide")
  var dotsBox = root.querySelector(".dots")
  var n = slides.length
  var i = 0
  var timer = null
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches
  var dots = []
  for (var k = 0; k < n; k++) {
    var d = document.createElement("button")
    d.type = "button"
    d.setAttribute("aria-label", "Show screenshot " + (k + 1))
    d.addEventListener("click", (function (idx) { return function () { go(idx) } })(k))
    dotsBox.appendChild(d)
    dots.push(d)
  }
  function go(to) {
    i = (to + n) % n
    track.style.transform = "translateX(" + -100 * i + "%)"
    slides.forEach(function (s, idx) { s.setAttribute("aria-hidden", idx === i ? "false" : "true") })
    dots.forEach(function (d, idx) { d.setAttribute("aria-current", idx === i ? "true" : "false") })
    var img = slides[(i + 1) % n].querySelector("img")
    if (img) img.loading = "eager"
  }
  function start() {
    if (reduce || timer) return
    timer = setInterval(function () { go(i + 1) }, 4500)
  }
  function stop() { clearInterval(timer); timer = null }
  root.querySelector(".prev").addEventListener("click", function () { go(i - 1) })
  root.querySelector(".next").addEventListener("click", function () { go(i + 1) })
  root.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") go(i - 1)
    if (e.key === "ArrowRight") go(i + 1)
  })
  root.addEventListener("mouseenter", stop)
  root.addEventListener("mouseleave", start)
  root.addEventListener("focusin", stop)
  root.addEventListener("focusout", start)
  document.addEventListener("visibilitychange", function () { document.hidden ? stop() : start() })
  go(0)
  start()
})()
