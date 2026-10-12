<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Worker test assets

`silence.opus`: 2 s of digital silence, Ogg/Opus, mono, 48 kHz, 8 kb/s (910 bytes), the audio that `FakeDownloader` writes (an allowed archive format, SPEC §11). Generated once, not recorded from anything, and dedicated to the public domain (CC0-1.0, see `silence.opus.license`). Made with FFmpeg 8.1 and libopus:

```sh
ffmpeg -f lavfi -i "anullsrc=r=48000:cl=mono" -t 2 -c:a libopus -b:a 8k \
  -map_metadata -1 -fflags +bitexact -flags:a +bitexact silence.opus
```

SHA-256 `265dca7975cb22805625c6b38c2ba96edbac940885a89ff6d61a2add61e648d6` (checked by `tests/worker/test_fake_downloader.py`). Do not replace it without updating that hash.
