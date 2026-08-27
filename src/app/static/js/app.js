// Presentation-only, and it stays this small: the server already renders the
// Suggest dialog open as an inline panel, and every control in it works with
// this script removed. This just upgrades that same markup into a true
// modal — backdrop, Esc, focus trap — all of which <dialog> provides itself.
const d = document.querySelector("dialog.calc-modal[open]");
if (d && typeof d.showModal === "function") {
  d.close();
  d.showModal();
}
