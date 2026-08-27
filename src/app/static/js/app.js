// Presentation-only, and it stays this small: the server already renders the
// Suggest dialog open as an inline panel, and every control in it works with
// this script removed. This just upgrades that same markup into a true
// modal — backdrop, Esc, focus trap — all of which <dialog> provides itself.
const d = document.querySelector("dialog.calc-modal[open]");
if (d && typeof d.showModal === "function") {
  d.close();
  d.showModal();
}

// Hide the second opener field when "One entry" is selected. `hidden` on the
// wrapper only — never `disabled` on the input. A disabled field stops
// posting, which would make this script load-bearing: the server must decide
// from the radio alone, so entry_1b keeps posting (and being ignored) either
// way, with or without this script running.
const openerRadios = document.querySelectorAll('input[name="opener_count"]');
const secondOpener = document.querySelector('[data-opener="second"]');
if (openerRadios.length && secondOpener) {
  const sync = () => {
    const one = document.querySelector('input[name="opener_count"]:checked')?.value === "1";
    secondOpener.hidden = one;
  };
  openerRadios.forEach((radio) => radio.addEventListener("change", sync));
  sync();
}
