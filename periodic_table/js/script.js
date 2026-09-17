function livelyPropertyListener(name, val) {
  // or switch-case...
  if (name == "multiplier") {
    document.documentElement.style.setProperty('--multiplier',`${val/10}`)
  } else if (name == "width") {
    document.documentElement.style.setProperty('--width',`${val}vw`)
  }
}
