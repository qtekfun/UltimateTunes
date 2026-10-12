// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The web player: queue (play now / next / later, reorder, remove, shuffle, repeat), HTML5
// <audio>, the full-screen "now playing" view, Media Session (lock-screen controls), synced
// lyrics, download state of `yt:` songs, scrobbles, keyboard shortcuts, the theme setting and
// focus management after HTMX navigation. Plain JavaScript, no build step, no eval, no
// innerHTML: every text from the server goes in with textContent. The page shell (with this
// player) stays while HTMX swaps #content, so the music keeps playing.
//
// Talks only to this server, with the session cookie: /web/stream, /web/cover, /web/api/*.
// State changes (scrobble, download) send the session's CSRF token in X-CSRF-Token.
// localStorage keeps display preferences only (volume, theme): never a key or a session.
(function () {
  "use strict";

  const audio = document.getElementById("audio");
  const player = document.getElementById("player");
  if (!audio || !player) {
    return;
  }
  const el = (id) => document.getElementById(id);
  const all = (selector) => Array.from(document.querySelectorAll(selector));
  const ui = {
    cover: el("p-cover"),
    title: el("p-title"),
    artist: el("p-artist"),
    status: el("p-status"),
    volume: el("p-volume"),
    np: el("nowplaying"),
    npBg: el("np-bg"),
    npArt: el("np-art"),
    npTitle: el("np-title"),
    npArtist: el("np-artist"),
    npAlbum: el("np-album"),
    lyricsPanel: el("lyrics-panel"),
    lyricsLines: el("lyrics-lines"),
    queuePanel: el("queue-panel"),
    queueList: el("queue-list"),
  };
  const text = (name) => player.dataset["t" + name] || "";
  const stateText = (state) => player.getAttribute("data-t-state-" + state) || "";
  const BLANK = "/web/static/blank.svg";
  const SVG = "http://www.w3.org/2000/svg";
  const POLL_MS = 1500;
  const POLL_LIMIT = 400; // about ten minutes
  const BADGE_POLL_MS = 4000;
  const SCROBBLE_AFTER_S = 240;
  const SEEK_STEP_S = 5;
  const VOLUME_STEP = 0.05;
  const REPEATS = ["off", "all", "one"];

  let queue = [];
  let index = -1;
  let repeat = "off";
  let nowSent = false;
  let scrobbled = false;
  let dragging = false;
  let pollTimer = null;
  let badgeTimer = null;
  let lyrics = null; // {for, synced, lines, current}
  let lastFocus = null;
  let dragFrom = -1;

  // ------------------------------------------------------------------ helpers

  function csrf() {
    const meta = document.querySelector('meta[name="ut-csrf"]');
    return meta ? meta.content : "";
  }

  function coverUrl(id) {
    return id ? "/web/cover/" + encodeURIComponent(id) : BLANK;
  }

  function clock(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const m = Math.floor(s / 60);
    return m + ":" + String(s % 60).padStart(2, "0");
  }

  function songOf(node) {
    try {
      return JSON.parse(node.dataset.song);
    } catch (e) {
      return null;
    }
  }

  function songsIn(list) {
    return Array.from(list.querySelectorAll("[data-song]")).map(songOf).filter(Boolean);
  }

  function getJson(url) {
    return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then((r) => (r.ok ? r.json() : Promise.reject(r)));
  }

  function post(url, data) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrf(), "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(data || {}),
    });
  }

  function setStatus(message) {
    ui.status.textContent = message || "";
  }

  function showError(response) {
    if (response && typeof response.json === "function") {
      response
        .json()
        .then((body) => setStatus(body.message || text("Error")))
        .catch(() => setStatus(text("Error")));
    } else {
      setStatus(text("Error"));
    }
  }

  function current() {
    return index >= 0 && index < queue.length ? queue[index] : null;
  }

  function shuffle(values) {
    const out = values.slice();
    for (let i = out.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [out[i], out[j]] = [out[j], out[i]];
    }
    return out;
  }

  function duration() {
    const song = current();
    return Number.isFinite(audio.duration) ? audio.duration : (song && song.duration) || 0;
  }

  function play() {
    if (current()) {
      audio.play().catch(() => undefined);
    }
  }

  function togglePlay() {
    if (!current()) {
      return;
    }
    if (audio.paused) {
      play();
    } else {
      audio.pause();
    }
  }

  // ------------------------------------------------------------------ queue

  function playList(songs, start) {
    if (!songs.length) {
      return;
    }
    queue = songs.slice();
    load(start || 0);
  }

  function playNext(song) {
    if (!current()) {
      playList([song], 0);
      return;
    }
    queue.splice(index + 1, 0, song);
    renderQueue();
  }

  function playLater(song) {
    if (!current()) {
      playList([song], 0);
      return;
    }
    queue.push(song);
    renderQueue();
  }

  function load(i) {
    if (i < 0 || i >= queue.length) {
      return;
    }
    index = i;
    const song = queue[i];
    nowSent = false;
    scrobbled = false;
    audio.src = "/web/stream/" + encodeURIComponent(song.id);
    play();
    showSong(song);
    watchStatus(song);
    renderQueue();
    markCurrent();
    if (!ui.lyricsPanel.hidden) {
      loadLyrics(song);
    }
  }

  function next(automatic) {
    if (automatic && repeat === "one") {
      audio.currentTime = 0;
      play();
    } else if (index + 1 < queue.length) {
      load(index + 1);
    } else if (repeat === "all" && queue.length) {
      load(0);
    } else {
      audio.pause();
    }
  }

  function previous() {
    if (audio.currentTime > 3 || index <= 0) {
      audio.currentTime = 0;
    } else {
      load(index - 1);
    }
  }

  function move(from, to) {
    if (from === to || from < 0 || to < 0 || from >= queue.length || to >= queue.length) {
      return;
    }
    const [song] = queue.splice(from, 1);
    queue.splice(to, 0, song);
    if (index === from) {
      index = to;
    } else if (from < index && to >= index) {
      index -= 1;
    } else if (from > index && to <= index) {
      index += 1;
    }
    renderQueue();
  }

  function removeAt(i) {
    if (i === index) {
      queue.splice(i, 1);
      if (queue.length) {
        load(Math.min(i, queue.length - 1));
      } else {
        index = -1;
        audio.pause();
        audio.removeAttribute("src");
      }
    } else {
      queue.splice(i, 1);
      if (i < index) {
        index -= 1;
      }
    }
    renderQueue();
  }

  function shuffleQueue() {
    const song = current();
    if (!song) {
      return;
    }
    const rest = queue.filter((_s, i) => i !== index);
    queue = [song].concat(shuffle(rest));
    index = 0;
    renderQueue();
  }

  function cycleRepeat() {
    repeat = REPEATS[(REPEATS.indexOf(repeat) + 1) % REPEATS.length];
    const label = player.getAttribute("data-t-repeat-" + repeat) || "";
    all("[data-act=repeat]").forEach((button) => {
      button.classList.toggle("active", repeat !== "off");
      button.classList.toggle("one", repeat === "one");
      button.setAttribute("aria-label", label);
      button.title = label;
    });
  }

  function startRadio(seedId, seed) {
    setStatus(text("Radio"));
    getJson("/web/api/radio/" + encodeURIComponent(seedId))
      .then((data) => {
        setStatus("");
        const songs = (data.songs || []).filter((s) => !seed || s.id !== seed.id);
        playList(seed ? [seed].concat(songs) : songs, 0);
      })
      .catch((r) => showError(r));
  }

  // ------------------------------------------------------------------ now playing

  function showSong(song) {
    ui.title.textContent = song.title;
    ui.artist.textContent = song.artist;
    ui.npTitle.textContent = song.title;
    ui.npArtist.textContent = song.artist;
    ui.npAlbum.textContent = song.album || "";
    const src = coverUrl(song.cover);
    ui.cover.src = src;
    ui.npArt.src = src;
    ui.npBg.src = src;
    document.title = song.title + " · UltimateTunes";
    setStatus("");
    if ("mediaSession" in navigator && "MediaMetadata" in window) {
      navigator.mediaSession.metadata = new window.MediaMetadata({
        title: song.title,
        artist: song.artist,
        album: song.album || "",
        artwork: song.cover ? [{ src: src, sizes: "512x512" }] : [],
      });
    }
  }

  function markCurrent() {
    const song = current();
    all("#content .song").forEach((row) => {
      const isCurrent = Boolean(song && row.dataset.id === song.id);
      row.classList.toggle("current", isCurrent);
      const button = row.querySelector(".song-play");
      if (button && isCurrent) {
        button.setAttribute("aria-current", "true");
      } else if (button) {
        button.removeAttribute("aria-current");
      }
    });
  }

  function openNowPlaying() {
    if (!ui.np.hidden) {
      return;
    }
    lastFocus = document.activeElement;
    ui.np.hidden = false;
    const close = ui.np.querySelector("[data-act=collapse]");
    if (close) {
      close.focus();
    }
  }

  function closeNowPlaying() {
    if (ui.np.hidden) {
      return;
    }
    ui.np.hidden = true;
    if (lastFocus && document.contains(lastFocus)) {
      lastFocus.focus();
    }
  }

  // ------------------------------------------------------------------ download states

  // The first play of a song that is not archived yet: show the download as it happens.
  function watchStatus(song) {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    if (!song.id.startsWith("yt:")) {
      return;
    }
    let polls = 0;
    const poll = () => {
      if (current() !== song) {
        return;
      }
      getJson("/web/api/status/" + encodeURIComponent(song.id))
        .then((s) => {
          if (current() !== song) {
            return;
          }
          updateBadges(song.id, s.state);
          if (s.state === "ready") {
            setStatus("");
            return;
          }
          if (s.state === "failed") {
            setStatus(text("Failed") + (s.error && s.error.message ? " " + s.error.message : ""));
            return;
          }
          if (s.state === "queued") {
            setStatus(text("Queued"));
          } else if (s.state === "downloading" || s.state === "tagging") {
            setStatus(text("Fetching") + " " + Math.round((s.progress || 0) * 100) + "%");
          } else {
            setStatus(text("Fetching"));
          }
          polls += 1;
          if (polls < POLL_LIMIT) {
            pollTimer = setTimeout(poll, POLL_MS);
          }
        })
        .catch(() => undefined);
    };
    setStatus(text("Fetching"));
    pollTimer = setTimeout(poll, 300);
  }

  function updateBadges(id, state) {
    all("#content .song").forEach((row) => {
      if (row.dataset.id !== id) {
        return;
      }
      const badge = row.querySelector("[data-state]");
      if (badge && stateText(state)) {
        badge.dataset.state = state;
        badge.className = "badge state-" + state;
        badge.textContent = stateText(state);
      }
    });
  }

  // Badges of songs being downloaded refresh until they are done (one call for the page).
  function pollBadges() {
    if (badgeTimer) {
      clearTimeout(badgeTimer);
      badgeTimer = null;
    }
    const busy = all(
      '#content [data-state="queued"], #content [data-state="downloading"], #content [data-state="tagging"]',
    )
      .map((badge) => badge.closest("[data-id]"))
      .filter(Boolean)
      .map((row) => row.dataset.id);
    const ids = Array.from(new Set(busy)).slice(0, 60);
    if (!ids.length) {
      return;
    }
    const query = ids.map((id) => "id=" + encodeURIComponent(id)).join("&");
    badgeTimer = setTimeout(() => {
      getJson("/web/api/states?" + query)
        .then((states) => {
          Object.keys(states).forEach((id) => updateBadges(id, states[id].state));
          pollBadges();
        })
        .catch(() => undefined);
    }, BADGE_POLL_MS);
  }

  function download(song) {
    post("/web/api/request/" + encodeURIComponent(song.id))
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then((s) => {
        updateBadges(song.id, s.state);
        setStatus(text("Requested"));
        pollBadges();
      })
      .catch((r) => showError(r));
  }

  // ------------------------------------------------------------------ queue panel

  function iconButton(act, i, label, path) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button";
    button.dataset.act = act;
    button.dataset.index = String(i);
    button.setAttribute("aria-label", label);
    button.title = label;
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    const shape = document.createElementNS(SVG, "path");
    shape.setAttribute("d", path);
    svg.append(shape);
    button.append(svg);
    return button;
  }

  function renderQueue() {
    const list = ui.queueList;
    list.replaceChildren();
    if (!queue.length) {
      const empty = document.createElement("li");
      empty.className = "muted";
      empty.textContent = text("Empty");
      list.append(empty);
      return;
    }
    queue.forEach((song, i) => {
      const item = document.createElement("li");
      item.classList.toggle("current", i === index);
      item.draggable = true;
      item.dataset.index = String(i);
      const jump = document.createElement("button");
      jump.type = "button";
      jump.className = "jump";
      jump.dataset.act = "queue-jump";
      jump.dataset.index = String(i);
      jump.textContent = song.title + " · " + song.artist;
      if (i === index) {
        jump.setAttribute("aria-current", "true");
      }
      item.append(
        jump,
        iconButton("queue-up", i, text("Moveup"), "M12 6l6 6-1.4 1.4-3.6-3.6V20h-2V9.8l-3.6 3.6L6 12z"),
        iconButton("queue-down", i, text("Movedown"), "M12 18l-6-6 1.4-1.4 3.6 3.6V4h2v10.2l3.6-3.6L18 12z"),
        iconButton(
          "queue-remove",
          i,
          text("Remove"),
          "M6.4 5 12 10.6 17.6 5 19 6.4 13.4 12l5.6 5.6-1.4 1.4-5.6-5.6L6.4 19 5 17.6 10.6 12 5 6.4z",
        ),
      );
      list.append(item);
    });
  }

  ui.queueList.addEventListener("dragstart", (event) => {
    const item = event.target instanceof Element ? event.target.closest("li[data-index]") : null;
    if (!item) {
      return;
    }
    dragFrom = Number(item.dataset.index);
    item.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", item.dataset.index);
  });
  ui.queueList.addEventListener("dragover", (event) => {
    const item = event.target instanceof Element ? event.target.closest("li[data-index]") : null;
    if (item) {
      event.preventDefault();
      all("#queue-list .drop-target").forEach((x) => x.classList.remove("drop-target"));
      item.classList.add("drop-target");
    }
  });
  ui.queueList.addEventListener("drop", (event) => {
    const item = event.target instanceof Element ? event.target.closest("li[data-index]") : null;
    if (item && dragFrom >= 0) {
      event.preventDefault();
      move(dragFrom, Number(item.dataset.index));
    }
    dragFrom = -1;
  });
  ui.queueList.addEventListener("dragend", () => {
    dragFrom = -1;
    all("#queue-list .dragging, #queue-list .drop-target").forEach((x) =>
      x.classList.remove("dragging", "drop-target"),
    );
  });

  // ------------------------------------------------------------------ lyrics and panels

  function loadLyrics(song) {
    if (!song || (lyrics && lyrics.for === song.id)) {
      return;
    }
    lyrics = { for: song.id, synced: false, lines: [], current: -1 };
    ui.lyricsLines.replaceChildren();
    const loading = document.createElement("li");
    loading.className = "muted";
    loading.textContent = text("Loadinglyrics");
    ui.lyricsLines.append(loading);
    getJson("/web/api/lyrics/" + encodeURIComponent(song.id))
      .then((data) => {
        if (!lyrics || lyrics.for !== song.id) {
          return;
        }
        lyrics.synced = Boolean(data.synced);
        lyrics.lines = data.lines || [];
        renderLyrics();
      })
      .catch(() => renderLyrics());
  }

  function renderLyrics() {
    const list = ui.lyricsLines;
    list.replaceChildren();
    list.className = "lyrics " + (lyrics && lyrics.synced ? "synced" : "plain");
    if (!lyrics || !lyrics.lines.length) {
      const none = document.createElement("li");
      none.textContent = text("Nolyrics");
      list.append(none);
      return;
    }
    lyrics.lines.forEach((line, i) => {
      const item = document.createElement("li");
      item.textContent = line.text || "♪";
      if (lyrics.synced) {
        // Tap a line to jump to it.
        item.dataset.act = "lyric";
        item.dataset.index = String(i);
        item.tabIndex = 0;
      }
      list.append(item);
    });
    lyrics.current = -1;
    followLyrics();
  }

  function followLyrics() {
    if (!lyrics || !lyrics.synced || ui.lyricsPanel.hidden) {
      return;
    }
    const ms = audio.currentTime * 1000;
    let found = -1;
    for (let i = 0; i < lyrics.lines.length; i += 1) {
      if (lyrics.lines[i].start !== null && lyrics.lines[i].start <= ms) {
        found = i;
      }
    }
    if (found === lyrics.current) {
      return;
    }
    const items = ui.lyricsLines.children;
    if (lyrics.current >= 0 && items[lyrics.current]) {
      items[lyrics.current].classList.remove("on");
    }
    lyrics.current = found;
    if (found >= 0 && items[found]) {
      items[found].classList.add("on");
      items[found].scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }

  function markPanels() {
    all("[data-act=lyrics]").forEach((b) => b.setAttribute("aria-expanded", String(!ui.lyricsPanel.hidden)));
    all("[data-act=queue]").forEach((b) => b.setAttribute("aria-expanded", String(!ui.queuePanel.hidden)));
  }

  function openPanel(panel, other) {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      other.hidden = true;
      const heading = panel.querySelector("h2");
      if (heading) {
        heading.focus();
      }
    }
    markPanels();
  }

  function closePanels() {
    ui.lyricsPanel.hidden = true;
    ui.queuePanel.hidden = true;
    markPanels();
  }

  function toggleLyrics() {
    openPanel(ui.lyricsPanel, ui.queuePanel);
    if (!ui.lyricsPanel.hidden) {
      loadLyrics(current());
    }
  }

  function toggleQueue() {
    openPanel(ui.queuePanel, ui.lyricsPanel);
    renderQueue();
  }

  // ------------------------------------------------------------------ theme

  function applyTheme(value) {
    if (value === "light" || value === "dark") {
      document.documentElement.dataset.theme = value;
    } else {
      delete document.documentElement.dataset.theme;
    }
    try {
      localStorage.setItem("ut.theme", value);
    } catch (e) {
      // Storage may be unavailable (private windows); the choice lasts for this page only.
    }
  }

  function markTheme() {
    let theme = "system";
    try {
      theme = localStorage.getItem("ut.theme") || "system";
    } catch (e) {
      // See applyTheme.
    }
    all("input[data-act=theme]").forEach((input) => {
      input.checked = input.value === theme;
    });
  }

  // ------------------------------------------------------------------ clicks and changes

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-act]") : null;
    if (!target || target.tagName === "INPUT") {
      return;
    }
    const act = target.dataset.act;
    const row = target.closest("[data-song]");
    const song = row ? songOf(row) : null;
    const menu = target.closest("details");
    if (menu) {
      menu.open = false;
    }
    switch (act) {
      case "play": {
        const list = row && row.closest("[data-songlist]");
        const rows = list ? Array.from(list.querySelectorAll("[data-song]")) : [row];
        playList(list ? songsIn(list) : [song], Math.max(0, rows.indexOf(row)));
        break;
      }
      case "play-all":
      case "shuffle-all": {
        const list = document.querySelector("#content [data-songlist]");
        if (list) {
          const songs = songsIn(list);
          playList(act === "shuffle-all" ? shuffle(songs) : songs, 0);
        }
        break;
      }
      case "next":
        if (song) {
          playNext(song);
        }
        break;
      case "later":
        if (song) {
          playLater(song);
        }
        break;
      case "radio":
        if (song) {
          startRadio(song.id, song);
        }
        break;
      case "download":
        if (song) {
          download(song);
        }
        break;
      case "artist-radio":
      case "seed-radio":
        startRadio(target.dataset.id, null);
        break;
      case "np-radio":
        if (current()) {
          startRadio(current().id, current());
        }
        break;
      case "toggle":
        togglePlay();
        break;
      case "prev":
        previous();
        break;
      case "next-track":
        next(false);
        break;
      case "shuffle-queue":
        shuffleQueue();
        break;
      case "repeat":
        cycleRepeat();
        break;
      case "expand":
        openNowPlaying();
        break;
      case "collapse":
        closeNowPlaying();
        break;
      case "lyrics":
        toggleLyrics();
        break;
      case "queue":
        toggleQueue();
        break;
      case "queue-jump":
        load(Number(target.dataset.index));
        break;
      case "queue-up":
        move(Number(target.dataset.index), Number(target.dataset.index) - 1);
        break;
      case "queue-down":
        move(Number(target.dataset.index), Number(target.dataset.index) + 1);
        break;
      case "queue-remove":
        removeAt(Number(target.dataset.index));
        break;
      case "clear-queue":
        queue = current() ? [current()] : [];
        index = queue.length ? 0 : -1;
        renderQueue();
        break;
      case "lyric": {
        const line = lyrics && lyrics.lines[Number(target.dataset.index)];
        if (line && line.start !== null) {
          audio.currentTime = line.start / 1000;
        }
        break;
      }
      default:
    }
  });

  document.addEventListener("change", (event) => {
    const input = event.target;
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    if (input.dataset.act === "theme") {
      applyTheme(input.value);
    } else if (input.hasAttribute("data-seek")) {
      dragging = false;
      audio.currentTime = Number(input.value);
    }
  });

  document.addEventListener("input", (event) => {
    const input = event.target;
    if (input instanceof HTMLInputElement && input.hasAttribute("data-seek")) {
      dragging = true;
      all("[data-time]").forEach((span) => {
        span.textContent = clock(Number(input.value));
      });
    }
  });

  // ------------------------------------------------------------------ audio

  audio.addEventListener("play", () => document.body.classList.add("playing"));
  audio.addEventListener("pause", () => document.body.classList.remove("playing"));
  audio.addEventListener("ended", () => next(true));
  audio.addEventListener("error", () => {
    if (current() && audio.getAttribute("src")) {
      setStatus(text("Unplayable"));
    }
  });
  audio.addEventListener("loadedmetadata", () => {
    const total = duration();
    all("[data-seek]").forEach((input) => {
      input.max = String(Math.floor(total));
    });
    all("[data-dur]").forEach((span) => {
      span.textContent = clock(total);
    });
  });
  audio.addEventListener("timeupdate", () => {
    const song = current();
    const t = audio.currentTime;
    if (!dragging) {
      all("[data-seek]").forEach((input) => {
        input.value = String(Math.floor(t));
      });
      all("[data-time]").forEach((span) => {
        span.textContent = clock(t);
      });
    }
    if (!song) {
      return;
    }
    if (!nowSent && t > 1) {
      nowSent = true;
      post("/web/api/scrobble", { id: song.id, submission: "false" }).catch(() => undefined);
    }
    const total = duration();
    if (!scrobbled && (t >= SCROBBLE_AFTER_S || (total > 0 && t >= total / 2))) {
      scrobbled = true;
      post("/web/api/scrobble", { id: song.id, submission: "true" }).catch(() => undefined);
    }
    followLyrics();
    if ("mediaSession" in navigator && navigator.mediaSession.setPositionState && total > 0) {
      try {
        navigator.mediaSession.setPositionState({
          duration: total,
          playbackRate: audio.playbackRate,
          position: Math.min(t, total),
        });
      } catch (e) {
        // Some browsers refuse while the duration is still growing (streaming while downloading).
      }
    }
  });

  function setVolume(value) {
    const volume = Math.min(1, Math.max(0, value));
    audio.volume = volume;
    ui.volume.value = String(volume);
    try {
      localStorage.setItem("ut.volume", String(volume));
    } catch (e) {
      // Storage may be unavailable (private windows); the volume just is not remembered.
    }
  }
  ui.volume.addEventListener("input", () => setVolume(Number(ui.volume.value)));
  try {
    const saved = localStorage.getItem("ut.volume");
    if (saved !== null && Number.isFinite(Number(saved))) {
      ui.volume.value = saved;
      audio.volume = Math.min(1, Math.max(0, Number(saved)));
    }
  } catch (e) {
    // See setVolume.
  }

  if ("mediaSession" in navigator) {
    const actions = {
      play: play,
      pause: () => audio.pause(),
      previoustrack: previous,
      nexttrack: () => next(false),
      seekbackward: () => {
        audio.currentTime = Math.max(0, audio.currentTime - 10);
      },
      seekforward: () => {
        audio.currentTime += 10;
      },
      seekto: (details) => {
        audio.currentTime = details.seekTime || 0;
      },
    };
    Object.keys(actions).forEach((name) => {
      try {
        navigator.mediaSession.setActionHandler(name, actions[name]);
      } catch (e) {
        // Not supported by this browser.
      }
    });
  }

  // ------------------------------------------------------------------ keyboard

  function typing(target) {
    if (!(target instanceof Element)) {
      return false;
    }
    const field = target.closest("input, textarea, select, [contenteditable]");
    return Boolean(field) && !(field instanceof HTMLInputElement && field.type === "range");
  }

  function focusSearch() {
    const input = el("search-input");
    if (input) {
      input.focus();
      input.select();
      return;
    }
    const link = document.querySelector('[data-nav][href="/web/search"]');
    if (link) {
      link.click();
    }
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!ui.lyricsPanel.hidden || !ui.queuePanel.hidden) {
        closePanels();
      } else {
        closeNowPlaying();
      }
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) {
      return;
    }
    const onControl = event.target instanceof Element && event.target.closest("button, a, summary");
    switch (event.key) {
      case " ":
        if (onControl) {
          return;
        }
        event.preventDefault();
        togglePlay();
        break;
      case "ArrowLeft":
      case "ArrowRight": {
        if (!current()) {
          return;
        }
        event.preventDefault();
        const forward = event.key === "ArrowRight";
        if (event.shiftKey && forward) {
          next(false);
        } else if (event.shiftKey) {
          previous();
        } else {
          audio.currentTime = Math.max(0, audio.currentTime + (forward ? SEEK_STEP_S : -SEEK_STEP_S));
        }
        break;
      }
      case "ArrowUp":
      case "ArrowDown":
        event.preventDefault();
        setVolume(audio.volume + (event.key === "ArrowUp" ? VOLUME_STEP : -VOLUME_STEP));
        break;
      case "/":
        event.preventDefault();
        focusSearch();
        break;
      case "f":
      case "F":
        if (ui.np.hidden) {
          openNowPlaying();
        } else {
          closeNowPlaying();
        }
        break;
      case "l":
      case "L":
        toggleLyrics();
        break;
      case "q":
      case "Q":
        toggleQueue();
        break;
      default:
    }
  });

  // ------------------------------------------------------------------ navigation and errors

  // Failed navigations and forms show the server's error page in #content; any other failed
  // HTMX request (a star) shows its message in the player's status line.
  document.body.addEventListener("htmx:beforeSwap", (event) => {
    const detail = event.detail;
    if (detail.xhr.status < 400) {
      return;
    }
    if (detail.target && detail.target.id === "content") {
      detail.shouldSwap = true;
      detail.isError = false;
      return;
    }
    let message = text("Error");
    try {
      message = JSON.parse(detail.xhr.responseText).message || message;
    } catch (e) {
      // Not JSON: keep the generic message.
    }
    setStatus(message);
  });
  document.body.addEventListener("htmx:sendError", () => setStatus(text("Error")));

  // A cover that cannot be loaded (no image yet, catalog unreachable) shows the placeholder,
  // also for the images that failed before this script ran.
  function placeholder(img) {
    if (img instanceof HTMLImageElement && !img.src.endsWith(BLANK)) {
      img.src = BLANK;
    }
  }
  document.addEventListener("error", (event) => placeholder(event.target), true);
  Array.from(document.images)
    .filter((img) => img.complete && img.naturalWidth === 0)
    .forEach(placeholder);

  // Highlight the section of the current page.
  function markNav() {
    const path = window.location.pathname;
    const home = path === "/" || path === "/web" || path === "/web/";
    let best = null;
    all("[data-nav]").forEach((link) => {
      const href = link.getAttribute("href");
      const matches = href === "/" ? home : path === href || path.startsWith(href + "/");
      if (matches && (!best || href.length > best.length)) {
        best = href;
      }
    });
    all("[data-nav]").forEach((link) => {
      if (best && link.getAttribute("href") === best) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  function afterPage(focus) {
    markNav();
    markCurrent();
    markTheme();
    pollBadges();
    if (focus) {
      // Move focus to the new page's heading, so screen readers announce it (an empty search
      // box takes it instead: the page is there to type in).
      const search = el("search-input");
      const heading = document.querySelector("#content h1");
      if (search && !search.value) {
        search.focus({ preventScroll: true });
      } else if (heading) {
        heading.focus({ preventScroll: true });
      }
    }
  }
  document.body.addEventListener("htmx:afterSettle", (event) => {
    const target = event.detail && event.detail.target;
    if (target && target.id === "content") {
      closeNowPlaying();
      afterPage(true);
    } else {
      pollBadges();
    }
  });
  window.addEventListener("popstate", () => setTimeout(() => afterPage(false), 0));
  afterPage(false);
  renderQueue();
})();
