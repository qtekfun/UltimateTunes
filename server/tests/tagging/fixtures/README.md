<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Tagging test audio

Generated tones (1 s, 440 Hz sine, stereo), not recorded from anything, dedicated to the public domain (CC0-1.0, see the `.license` files). Made with FFmpeg 8.1 (libopus, libvorbis, native AAC) and `-map_metadata -1 -fflags +bitexact -flags:a +bitexact`:

| File | Stands for | Made with |
| --- | --- | --- |
| `tone.webm` | format 251 (Opus in WebM) | `-f lavfi -i sine=frequency=440:sample_rate=48000:duration=1 -ac 2 -c:a libopus -b:a 16k` |
| `tone.m4a` | format 140 (AAC in fragmented MP4, as YouTube serves it) | the same tone at 44.1 kHz, `-c:a aac -b:a 32k -movflags +frag_keyframe+empty_moov+default_base_moof` |
| `vorbis.webm` | an unsupported codec (Vorbis in WebM) | `-c:a libvorbis -b:a 64k` |
| `tone.opus` | the Ogg/Opus archive of `tone.webm` | `-i tone.webm -map 0:a:0 -c:a copy -map_metadata -1 -fflags +bitexact -f ogg` |
| `tone-faststart.m4a` | the M4A archive of `tone.m4a` | `-i tone.m4a -map 0:a:0 -c:a copy -map_metadata -1 -fflags +bitexact -movflags +faststart -f mp4` |

`tone.opus` and `tone-faststart.m4a` let the mutagen tests run without FFmpeg; the golden tests that need FFmpeg are skipped when it is not installed.
