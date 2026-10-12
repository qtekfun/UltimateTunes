// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Runs before the first paint (not deferred): applies the theme chosen in Settings, kept in
// this browser only ("light", "dark"; nothing or "system" follows the system). A display
// preference: it never leaves the browser.
(function () {
  "use strict";
  try {
    const theme = localStorage.getItem("ut.theme");
    if (theme === "light" || theme === "dark") {
      document.documentElement.dataset.theme = theme;
    }
  } catch (e) {
    // Storage may be unavailable (private windows): the system's theme applies.
  }
})();
