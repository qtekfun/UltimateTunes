#!/bin/sh
# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Tools stage of server/Dockerfile (never shipped): fetches Deno and the yt-dlp seed zipapp,
# verifies them and lays them out under /out. Every check fails closed: any mismatch stops the
# build. Inputs come from the Dockerfile's ARGs (environment):
#   TARGETARCH, DENO_VERSION, DENO_SHA256_AMD64, DENO_SHA256_ARM64,
#   YTDLP_SEED_VERSION, YTDLP_SEED_SHA256, YTDLP_SIGNER_FPR
# Output:
#   /out/bin/deno
#   /out/share/yt-dlp-keyring.gpg     binary keyring for gpgv (the worker's updater uses it, T08)
#   /out/ytdlp-seed/{yt-dlp,SHA2-256SUMS,SHA2-256SUMS.sig,VERSION}
set -eu

here=$(dirname "$0")
fetch() { python -I "$here/fetch.py" "$@"; }
work=$(mktemp -d)
export GNUPGHOME="$work/gnupg"
mkdir -m 0700 "$GNUPGHOME"
mkdir -p /out/bin /out/share /out/ytdlp-seed

# --- Deno: pinned version and per-architecture SHA-256 -------------------------------------
case "${TARGETARCH:?}" in
    amd64) triple=x86_64-unknown-linux-gnu; deno_sha=${DENO_SHA256_AMD64:?} ;;
    arm64) triple=aarch64-unknown-linux-gnu; deno_sha=${DENO_SHA256_ARM64:?} ;;
    *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;;
esac
fetch "https://github.com/denoland/deno/releases/download/v${DENO_VERSION:?}/deno-${triple}.zip" \
    "$work/deno.zip" "$deno_sha"
python -I -m zipfile -e "$work/deno.zip" "$work/deno"
install -m 0755 "$work/deno/deno" /out/bin/deno

# --- yt-dlp release key: the committed file must hold exactly the pinned key ----------------
want_fpr=$(printf '%s' "${YTDLP_SIGNER_FPR:?}" | tr -d ' ')
[ "${#want_fpr}" -eq 40 ] || { echo "YTDLP_SIGNER_FPR is not a 40-hex fingerprint" >&2; exit 1; }
key_fprs=$(gpg --batch --with-colons --show-keys "$here/yt-dlp-public.key" | awk -F: '$1 == "fpr" { print $10 }')
primary_fpr=$(printf '%s\n' "$key_fprs" | head -n 1)
[ "$primary_fpr" = "$want_fpr" ] || {
    echo "yt-dlp-public.key fingerprint '$primary_fpr' is not the pinned '$want_fpr'" >&2; exit 1; }
[ "$(gpg --batch --with-colons --show-keys "$here/yt-dlp-public.key" | grep -c '^pub:')" -eq 1 ] || {
    echo "yt-dlp-public.key must contain exactly one key" >&2; exit 1; }
# A plain binary keyring (not a keybox): what gpgv reads with --keyring.
gpg --batch --yes --dearmor --output /out/share/yt-dlp-keyring.gpg "$here/yt-dlp-public.key"

# --- yt-dlp seed: signature over SHA2-256SUMS, then the pinned SHA-256 ----------------------
rel="https://github.com/yt-dlp/yt-dlp/releases/download/${YTDLP_SEED_VERSION:?}"
fetch "$rel/SHA2-256SUMS" "$work/SHA2-256SUMS"
fetch "$rel/SHA2-256SUMS.sig" "$work/SHA2-256SUMS.sig"
gpgv --status-fd 3 --keyring /out/share/yt-dlp-keyring.gpg \
    "$work/SHA2-256SUMS.sig" "$work/SHA2-256SUMS" 3>"$work/gpgv.status"
grep -q "^\[GNUPG:\] VALIDSIG ${want_fpr} " "$work/gpgv.status" || {
    echo "SHA2-256SUMS is not signed by ${want_fpr}" >&2; cat "$work/gpgv.status" >&2; exit 1; }
signed_sha=$(awk '$2 == "yt-dlp" { print $1 }' "$work/SHA2-256SUMS")
[ "$signed_sha" = "${YTDLP_SEED_SHA256:?}" ] || {
    echo "signed SHA-256 of yt-dlp '$signed_sha' is not the pinned '$YTDLP_SEED_SHA256'" >&2; exit 1; }
fetch "$rel/yt-dlp" "$work/yt-dlp" "$YTDLP_SEED_SHA256"
install -m 0755 "$work/yt-dlp" /out/ytdlp-seed/yt-dlp
install -m 0644 "$work/SHA2-256SUMS" "$work/SHA2-256SUMS.sig" /out/ytdlp-seed/
printf '%s\n' "$YTDLP_SEED_VERSION" >/out/ytdlp-seed/VERSION

rm -rf "$work"
