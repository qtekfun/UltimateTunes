# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generates an invented music library for the measurements (PLAN T21, docs/measurements.md).

Every file is the 2 s silent CC0 Opus clip of the fake downloader with invented Vorbis tags, so
50,000 tracks take about 200 MB on disk and no real music is involved. Names come from a fixed
seed: the same arguments always give the same library.

    uv run --project server python tools/bench/gen_library.py OUT_DIR [--tracks 50000]
        [--per-album 10] [--albums-per-artist 2] [--seed 21]

Layout: `OUT_DIR/<Artist>/<Album>/NN - <Title>.opus` (the archive layout of the server).
It also writes `OUT_DIR/../bench-queries.txt`: one artist, album or title word per line, used by
the search benchmarks (`library_bench.py --queries`).
"""

import argparse
import random
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import mutagen.oggopus

import ultimatetunes.worker as worker_pkg

SILENCE = Path(worker_pkg.__file__).parent / "assets" / "silence.opus"
GENRES = [
    "Indie Pop", "Synthwave", "Folk", "Jazz", "Latin Pop", "Ambient", "Hard Rock", "Soul",
    "Hip Hop", "Bossa Nova", "Techno", "Chamber Pop", "Flamenco", "Reggae", "Post-Punk",
]  # fmt: skip
_ONSET = ["b", "br", "c", "ch", "d", "dr", "f", "g", "gl", "h", "j", "k", "l", "m", "n", "p",
          "pl", "r", "s", "st", "t", "tr", "v", "w", "z"]  # fmt: skip
_VOWEL = ["a", "e", "i", "o", "u", "ai", "ea", "io", "ou"]
_CODA = ["", "", "n", "r", "s", "l", "th", "m", "x"]
_WORDS = [
    "Lantern", "Harbour", "Velvet", "Static", "Orchard", "Ferry", "Signal", "Ember", "Tide",
    "Glass", "Paper", "Neon", "Salt", "Moon", "River", "Copper", "Winter", "Garden", "Echo",
    "Satellite", "Meadow", "Cinder", "Arcade", "Lighthouse", "Comet", "Saffron", "Marble",
    "Hollow", "Silver", "Thunder", "Paradise", "Midnight", "Coral", "Atlas", "Prism", "Dune",
]  # fmt: skip


def word(rng: random.Random) -> str:
    syllables = rng.randint(2, 3)
    text = "".join(
        rng.choice(_ONSET) + rng.choice(_VOWEL) + rng.choice(_CODA) for _ in range(syllables)
    )
    return text.capitalize()


def phrase(rng: random.Random, low: int, high: int) -> str:
    parts = [rng.choice(_WORDS) if rng.random() < 0.5 else word(rng)]
    parts += [word(rng) if rng.random() < 0.6 else rng.choice(_WORDS)
              for _ in range(rng.randint(low, high) - 1)]  # fmt: skip
    return " ".join(parts)


def unique(rng: random.Random, seen: set[str], make: Callable[[random.Random], str]) -> str:
    while True:
        value = make(rng)
        if value.lower() not in seen:
            seen.add(value.lower())
            return value


def generate(out: Path, tracks: int, per_album: int, albums_per_artist: int, seed: int) -> int:
    rng = random.Random(seed)  # noqa: S311 - invented names, not security
    out.mkdir(parents=True, exist_ok=True)
    artists_seen: set[str] = set()
    queries: list[str] = []
    written = 0
    while written < tracks:
        artist = unique(rng, artists_seen, lambda r: phrase(r, 1, 3))
        if rng.random() < 0.3:
            artist = "The " + artist
        genre = rng.choice(GENRES)
        queries.append(artist.split()[-1])
        for _ in range(albums_per_artist):
            if written >= tracks:
                break
            album = phrase(rng, 1, 4)
            year = rng.randint(1965, 2026)
            album_dir = out / artist / album
            album_dir.mkdir(parents=True, exist_ok=True)
            count = min(per_album, tracks - written)
            queries.append(album.split()[0])
            for n in range(1, count + 1):
                title = phrase(rng, 1, 5)
                path = album_dir / f"{n:02d} - {title}.opus"
                shutil.copyfile(SILENCE, path)
                audio = mutagen.oggopus.OggOpus(path)  # type: ignore[no-untyped-call]
                audio["title"] = [title]
                audio["artist"] = [artist]
                audio["albumartist"] = [artist]
                audio["album"] = [album]
                audio["tracknumber"] = [f"{n}/{count}"]
                audio["date"] = [str(year)]
                audio["genre"] = [genre]
                audio.save()
                written += 1
                if n == 1:
                    queries.append(title.split()[-1])
        if written % 5000 < per_album * albums_per_artist:
            print(f"{written} tracks", file=sys.stderr)
    rng.shuffle(queries)
    (out.parent / "bench-queries.txt").write_text("\n".join(queries) + "\n", encoding="utf-8")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--tracks", type=int, default=50_000)
    parser.add_argument("--per-album", type=int, default=10)
    parser.add_argument("--albums-per-artist", type=int, default=2)
    parser.add_argument("--seed", type=int, default=21)
    args = parser.parse_args()
    n = generate(args.out, args.tracks, args.per_album, args.albums_per_artist, args.seed)
    print(f"generated {n} tracks in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
