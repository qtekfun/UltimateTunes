// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later
// Asks before destructive admin actions: any form with `data-confirm` shows that text in a
// confirmation dialog and is submitted only when accepted. Without JavaScript the forms still
// work (deletes also need their checkbox).
"use strict";
document.addEventListener("submit", function (event) {
  var form = event.target;
  var message = form && form.getAttribute ? form.getAttribute("data-confirm") : null;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});
