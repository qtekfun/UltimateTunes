// SPDX-FileCopyrightText: 2026 UltimateTunes contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The web player: queue, HTML5 <audio>, Media Session (lock-screen controls), synced lyrics,
// first-play status of `yt:` songs and scrobbles. Plain JavaScript, no build step, no eval and
// no innerHTML: every text from the server goes in with textContent. The page shell (with
// this player bar) stays while HTMX swaps #content, so the music keeps playing.
//
// Talks only to this server, with the session cookie: /web/stream, /web/cover, /web/api/*.
// State changes (scrobble) send the session's CSRF token in X-CSRF-Token.
(function () {
  "use strict";

  const audio = document.getElementById("audio");
  const player = document.getElementById("player");
  if (!audio || !player) {
    return;
  }
  const el = (id) => document.getElementById(id);
  const ui = {
    cover: el("p-cover"),
    title: el("p-title"),
    artist: el("p-artist"),
    status: el("p-status"),
    time: el("p-time"),
    dur: el("p-dur"),
    seek: el("p-seek"),
    volume: el("p-volume"),
    lyricsPanel: el("lyrics-panel"),
    lyricsLines: el("lyrics-lines"),
    queuePanel: el("queue-panel"),
    queueList: el("queue-list"),
  };
  const text = (name) => player.dataset["t" + name] || "";
  const POLL_MS = 1500;
  const POLL_LIMIT = 400; // about ten minutes
  const SCROBBLE_AFTER_S = 240;

  let queue = [];
  let index = -1;
  let nowSent = false;
  let scrobbled = false;
  let dragging = false;
  let pollTimer = null;
  let lyrics = null; // {for, synced, lines, current}

  // ------------------------------------------------------------------ helpers

  function csrf() {
    const meta = document.querySelector('meta[name="ut-csrf"]');
    return meta ? meta.content : "";
  }

  function coverUrl(id) {
    return id ? "/web/cover/" + encodeURIComponent(id) : "/web/static/blank.svg";
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
      body: new URLSearchParams(data),
    }).catch(() => undefined);
  }

  function setStatus(message) {
    ui.status.textContent = message || "";
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
    audio.play().catch(() => undefined);
    showSong(song);
    watchStatus(song);
    renderQueue();
    markCurrent();
    if (!ui.lyricsPanel.hidden) {
      loadLyrics(song);
    }
  }

  function next() {
    if (index + 1 < queue.length) {
      load(index + 1);
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

  function startRadio(seedId, seed) {
    setStatus(text("Radio"));
    getJson("/web/api/radio/" + encodeURIComponent(seedId))
      .then((data) => {
        setStatus("");
        const songs = (data.songs || []).filter((s) => !seed || s.id !== seed.id);
        playList(seed ? [seed].concat(songs) : songs, 0);
      })
      .catch(() => setStatus(text("Unplayable")));
  }

  // ------------------------------------------------------------------ now playing

  function showSong(song) {
    ui.title.textContent = song.title;
    ui.artist.textContent = song.artist;
    ui.cover.src = coverUrl(song.cover);
    document.title = song.title + " · UltimateTunes";
    setStatus("");
    if ("mediaSession" in navigator && "MediaMetadata" in window) {
      navigator.mediaSession.metadata = new window.MediaMetadata({
        title: song.title,
        artist: song.artist,
        album: song.album || "",
        artwork: song.cover ? [{ src: coverUrl(song.cover), sizes: "512x512" }] : [],
      });
    }
  }

  function markCurrent() {
    const song = current();
    document.querySelectorAll("#content .song").forEach((row) => {
      const s = songOf(row);
      row.classList.toggle("current", Boolean(song && s && s.id === song.id));
    });
  }

  // First play of a song that is not archived yet: show the download as it happens.
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

  // ------------------------------------------------------------------ queue panel

  function renderQueue() {
    const list = ui.queueList;
    list.replaceChildren();
    if (!queue.length) {
      const empty = document.createElement("li");
      empty.textContent = text("Empty");
      list.append(empty);
      return;
    }
    queue.forEach((song, i) => {
      const item = document.createElement("li");
      item.classList.toggle("current", i === index);
      const jump = document.createElement("button");
      jump.type = "button";
      jump.className = "jump";
      jump.dataset.act = "queue-jump";
      jump.dataset.index = String(i);
      jump.textContent = song.title + " · " + song.artist;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "link";
      remove.dataset.act = "queue-remove";
      remove.dataset.index = String(i);
      remove.textContent = text("Remove");
      item.append(jump, remove);
      list.append(item);
    });
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

  // ------------------------------------------------------------------ lyrics

  function loadLyrics(song) {
    if (!song || (lyrics && lyrics.for === song.id)) {
      return;
    }
    lyrics = { for: song.id, synced: false, lines: [], current: -1 };
    ui.lyricsLines.replaceChildren();
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
        item.dataset.act = "lyric";
        item.dataset.index = String(i);
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

  function togglePanel(panel, other) {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      other.hidden = true;
    }
  }

  // ------------------------------------------------------------------ events

  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-act]") : null;
    if (!target) {
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
      case "artist-radio":
        startRadio(target.dataset.id, null);
        break;
      case "toggle":
        if (!current()) {
          return;
        }
        if (audio.paused) {
          audio.play().catch(() => undefined);
        } else {
          audio.pause();
        }
        break;
      case "prev":
        previous();
        break;
      case "next-track":
        next();
        break;
      case "lyrics":
        togglePanel(ui.lyricsPanel, ui.queuePanel);
        target.classList.toggle("active", !ui.lyricsPanel.hidden);
        if (!ui.lyricsPanel.hidden) {
          loadLyrics(current());
        }
        break;
      case "queue":
        togglePanel(ui.queuePanel, ui.lyricsPanel);
        renderQueue();
        break;
      case "queue-jump":
        load(Number(target.dataset.index));
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
        return;
    }
  });

  audio.addEventListener("play", () => player.classList.add("playing"));
  audio.addEventListener("pause", () => player.classList.remove("playing"));
  audio.addEventListener("ended", next);
  audio.addEventListener("error", () => {
    if (current() && audio.getAttribute("src")) {
      setStatus(text("Unplayable"));
    }
  });
  audio.addEventListener("loadedmetadata", () => {
    const duration = Number.isFinite(audio.duration) ? audio.duration : (current() || {}).duration || 0;
    ui.seek.max = String(Math.floor(duration));
    ui.dur.textContent = clock(duration);
  });
  audio.addEventListener("timeupdate", () => {
    const song = current();
    const t = audio.currentTime;
    if (!dragging) {
      ui.seek.value = String(Math.floor(t));
      ui.time.textContent = clock(t);
    }
    if (!song) {
      return;
    }
    if (!nowSent && t > 1) {
      nowSent = true;
      post("/web/api/scrobble", { id: song.id, submission: "false" });
    }
    const duration = Number.isFinite(audio.duration) ? audio.duration : song.duration;
    if (!scrobbled && (t >= SCROBBLE_AFTER_S || (duration > 0 && t >= duration / 2))) {
      scrobbled = true;
      post("/web/api/scrobble", { id: song.id, submission: "true" });
    }
    followLyrics();
    if ("mediaSession" in navigator && navigator.mediaSession.setPositionState && duration > 0) {
      try {
        navigator.mediaSession.setPositionState({
          duration: duration,
          playbackRate: audio.playbackRate,
          position: Math.min(t, duration),
        });
      } catch (e) {
        // Some browsers refuse while the duration is still growing (streaming while downloading).
      }
    }
  });
  ui.seek.addEventListener("input", () => {
    dragging = true;
    ui.time.textContent = clock(Number(ui.seek.value));
  });
  ui.seek.addEventListener("change", () => {
    dragging = false;
    audio.currentTime = Number(ui.seek.value);
  });
  ui.volume.addEventListener("input", () => {
    audio.volume = Number(ui.volume.value);
    try {
      localStorage.setItem("ut.volume", ui.volume.value);
    } catch (e) {
      // Storage may be unavailable (private windows); the volume just is not remembered.
    }
  });
  try {
    const saved = localStorage.getItem("ut.volume");
    if (saved !== null) {
      ui.volume.value = saved;
      audio.volume = Number(saved);
    }
  } catch (e) {
    // See above.
  }

  if ("mediaSession" in navigator) {
    const actions = {
      play: () => audio.play().catch(() => undefined),
      pause: () => audio.pause(),
      previoustrack: previous,
      nexttrack: next,
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

  document.addEventListener("keydown", (event) => {
    const tag = event.target instanceof Element ? event.target.tagName : "";
    if (event.code !== "Space" || ["INPUT", "TEXTAREA", "BUTTON", "SUMMARY"].includes(tag)) {
      return;
    }
    if (current()) {
      event.preventDefault();
      if (audio.paused) {
        audio.play().catch(() => undefined);
      } else {
        audio.pause();
      }
    }
  });

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
    let message = text("Unplayable");
    try {
      message = JSON.parse(detail.xhr.responseText).message || message;
    } catch (e) {
      // Not JSON: keep the generic message.
    }
    setStatus(message);
  });

  // A cover that cannot be loaded (no image yet, catalog unreachable) shows the placeholder,
  // also for the images that failed before this script ran.
  function placeholder(img) {
    if (img instanceof HTMLImageElement && !img.src.endsWith("/web/static/blank.svg")) {
      img.src = "/web/static/blank.svg";
    }
  }
  document.addEventListener("error", (event) => placeholder(event.target), true);
  Array.from(document.images)
    .filter((img) => img.complete && img.naturalWidth === 0)
    .forEach(placeholder);

  // Highlight the section of the current page, also after HTMX navigation.
  function markNav() {
    const path = window.location.pathname;
    const home = path === "/" || path === "/web" || path === "/web/";
    let best = null;
    document.querySelectorAll("[data-nav]").forEach((link) => {
      const href = link.getAttribute("href");
      const matches = href === "/" ? home : path === href || path.startsWith(href + "/");
      if (matches && (!best || href.length > best.getAttribute("href").length)) {
        best = link;
      }
      link.removeAttribute("aria-current");
    });
    if (best) {
      best.setAttribute("aria-current", "page");
    }
    markCurrent();
  }
  document.body.addEventListener("htmx:afterSettle", markNav);
  window.addEventListener("popstate", () => setTimeout(markNav, 0));
  markNav();
  renderQueue();
})();
