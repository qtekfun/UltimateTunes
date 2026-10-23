# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Optional PO token provider (D13): the setting's validation, the yt-dlp command line with and
without it, the plugin directory wiring, token redaction, and the pins in the Dockerfile and the
compose file staying on one upstream version. Nothing reaches the network."""

import importlib.util
import itertools
import re
import secrets
import zipfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ultimatetunes.core.limits import DownloadLimits
from ultimatetunes.core.storage import LocalStagingStore
from ultimatetunes.errors import WorkerErrorCode
from ultimatetunes.worker import settings as worker_settings
from ultimatetunes.worker import ytdlp
from ultimatetunes.worker.downloader import DownloadError, DownloadProgress
from ultimatetunes.worker.settings import WorkerSettings, internal_base_url
from ultimatetunes.worker.ytdlp import YtDlpDownloader, build_args, redact

pytestmark = pytest.mark.anyio
REPO = Path(__file__).resolve().parents[3]
FAKE_ZIPAPP = Path(__file__).parent / "fixtures" / "fake_ytdlp.py"
JOB_DIR = "0199d6a2-4c1e-7b3a-9f10-2a6c8e019002/1"
LIMITS = DownloadLimits(max_track_duration_s=1200, max_download_bytes=50_000_000)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------- the setting


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("http://pot-provider:4416", "http://pot-provider:4416"),
        ("  http://pot-provider:4416/  ", "http://pot-provider:4416"),
        ("HTTP://POT-Provider:4416", "http://pot-provider:4416"),
        ("https://bgutil", "https://bgutil"),
        ("http://localhost:4416", "http://localhost:4416"),
        ("http://127.0.0.1:4416", "http://127.0.0.1:4416"),
        ("http://10.213.47.2:4416", "http://10.213.47.2:4416"),
        ("http://172.18.0.5:4416", "http://172.18.0.5:4416"),
        ("http://192.168.1.20:4416", "http://192.168.1.20:4416"),
        ("http://[::1]:4416", "http://[::1]:4416"),
        ("http://[fd00::5]:4416", "http://[fd00::5]:4416"),
        ("http://[FD00:0:0::5]:4416", "http://[fd00::5]:4416"),
        ("http://172.31.255.254", "http://172.31.255.254"),
        ("http://127.0.0.2:4416", "http://127.0.0.2:4416"),
    ],
)
def test_internal_urls_are_accepted_in_canonical_form(raw: str, canonical: str) -> None:
    assert internal_base_url(raw) == canonical
    assert WorkerSettings(ytdlp_pot_provider_url=raw).ytdlp_pot_provider_url == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://pot-provider:4416",
        "file:///etc/passwd",
        "pot-provider:4416",
        "//pot-provider:4416",
        "http://",
        "http://user:pw@pot-provider:4416",
        "http://user@pot-provider:4416",
        "http://pot-provider:4416/get_pot",
        "http://pot-provider:4416/?x=1",
        "http://pot-provider:4416/#x",
        "http://pot-provider:99999",
        "http://pot-provider:port",
        # Public names and addresses: a dotted name needs DNS, which could lead anywhere.
        "http://example.com:4416",
        "http://pot-provider.example.com",
        "http://8.8.8.8:4416",
        "http://[2001:4860::8888]:4416",
        # Names an `inet_aton` resolver reads as an IPv4 address.
        "http://2130706433:4416",
        "http://0x7f000001:4416",
        "http://-pot:4416",
        # Link-local (cloud metadata), unspecified, multicast.
        "http://169.254.169.254",
        "http://[fe80::1]:4416",
        "http://0.0.0.0:4416",
        "http://[::]:4416",
        "http://224.0.0.1:4416",
        # Separators of yt-dlp's --extractor-args can never get through.
        "http://pot-provider:4416;base_url=http://8.8.8.8",
        "http://pot,provider:4416",
        # IPv6 zone ids would carry `%`, `,` or `;` into the argument.
        "http://[fd00::5%a;b=c]:1",
        "http://[fd00::5%25a,b]:4416",
        "http://[fe80::1%eth0]:4416",
        # Only 10/8, 172.16/12, 192.168/16, 127/8, ::1 and fc00::/7.
        "http://100.64.0.1:4416",
        "http://192.0.2.10:4416",
        "http://198.51.100.7:4416",
        "http://172.32.0.1:4416",
        "http://240.0.0.1:4416",
        "http://[::ffff:10.0.0.1]:4416",
        "http://[::ffff:127.0.0.1]:4416",
        "http://[2002:a00:1::1]:4416",
        "http://[64:ff9b::a00:1]:4416",
        # Port 0.
        "http://pot-provider:0",
    ],
)
def test_anything_but_an_internal_base_url_is_refused_at_load(raw: str) -> None:
    with pytest.raises(ValueError, match=r"URL|host"):
        internal_base_url(raw)
    with pytest.raises(ValidationError) as caught:
        WorkerSettings(ytdlp_pot_provider_url=raw)
    # Settings hide refused input: the value never reaches a log.
    assert raw not in str(caught.value)


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_or_blank_means_no_provider(raw: str | None) -> None:
    assert WorkerSettings(ytdlp_pot_provider_url=raw).ytdlp_pot_provider_url is None


def test_the_defaults_load_no_provider_and_point_at_the_image_plugin_dir() -> None:
    settings = WorkerSettings()
    assert settings.ytdlp_pot_provider_url is None
    assert settings.ytdlp_plugin_dir == Path("/opt/ytdlp-plugins")


def test_the_env_var_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UT_YTDLP_POT_PROVIDER_URL", "http://pot-provider:4416")
    monkeypatch.setenv("UT_YTDLP_PLUGIN_DIR", "/plugins")
    settings = WorkerSettings()
    assert settings.ytdlp_pot_provider_url == "http://pot-provider:4416"
    assert settings.ytdlp_plugin_dir == Path("/plugins")


# ---------------------------------------------------------------- the command line


def _args(tmp_path: Path, **extra: Any) -> list[str]:
    return build_args(
        python="/usr/bin/python3",
        zipapp=Path("/opt/ytdlp/current/yt-dlp"),
        deno=Path("/usr/local/bin/deno"),
        clients="default",
        out_dir=tmp_path,
        video_id="Qx7Lm2pZ0aB",
        limits=LIMITS,
        **extra,
    )


def test_without_a_provider_no_plugin_is_loaded(tmp_path: Path) -> None:
    args = _args(tmp_path)
    assert "--no-plugin-dirs" in args
    assert "--plugin-dirs" not in args
    assert not any("youtubepot" in a for a in args)
    # The plugin directory alone changes nothing.
    assert _args(tmp_path, plugin_dir=Path("/opt/ytdlp-plugins")) == args


def test_with_a_provider_only_the_image_plugin_dir_is_searched(tmp_path: Path) -> None:
    args = _args(
        tmp_path,
        pot_provider_url="http://pot-provider:4416",
        plugin_dir=Path("/opt/ytdlp-plugins"),
    )
    # The defaults are cleared first, then only our directory is added (order matters).
    cleared = args.index("--no-plugin-dirs")
    assert args[cleared + 1 : cleared + 3] == ["--plugin-dirs", "/opt/ytdlp-plugins"]
    assert args.count("--plugin-dirs") == 1
    extractor_args = [b for a, b in itertools.pairwise(args) if a == "--extractor-args"]
    assert extractor_args == [
        "youtube:player_client=default",
        "youtubepot-bgutilhttp:base_url=http://pot-provider:4416",
    ]
    assert args.index("--extractor-args") < args.index("--")
    # Everything else is the same command line, in the same order.
    without = _args(tmp_path)
    assert [a for a in args if a not in {"--plugin-dirs", "/opt/ytdlp-plugins"}] == [
        *without[: without.index("--format")],
        "--extractor-args",
        "youtubepot-bgutilhttp:base_url=http://pot-provider:4416",
        *without[without.index("--format") :],
    ]


@pytest.mark.parametrize(
    ("url", "plugin_dir"),
    [
        ("http://pot-provider:4416", None),
        ("http://pot-provider:4416/", Path("/p")),
        ("http://8.8.8.8:4416", Path("/p")),
        ("http://pot-provider:4416;x=y", Path("/p")),
        ("http://[fd00::5%a;b=c]:1", Path("/p")),
        ("http://[fd00::5%25a,b]:4416", Path("/p")),
    ],
)
def test_the_command_line_refuses_an_unchecked_provider(
    tmp_path: Path, url: str, plugin_dir: Path | None
) -> None:
    with pytest.raises(ValueError, match=r"URL|host|provider"):
        _args(tmp_path, pot_provider_url=url, plugin_dir=plugin_dir)


# ---------------------------------------------------------------- the downloader


class Zipapp:
    def current_zipapp(self) -> Path:
        return FAKE_ZIPAPP


async def _record(_report: DownloadProgress) -> None:
    return None


@pytest.fixture
def staging(tmp_path: Path) -> LocalStagingStore:
    root = tmp_path / "staging"
    root.mkdir()
    return LocalStagingStore(root)


async def test_the_downloader_passes_the_provider_and_plugin_dir(
    staging: LocalStagingStore, tmp_path: Path
) -> None:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    seen: list[list[str]] = []

    async def runner(args: list[str], env: dict[str, str]) -> Any:
        seen.append(args)
        return await ytdlp._open(args, env)

    settings = WorkerSettings(
        ytdlp_pot_provider_url="http://pot-provider:4416", ytdlp_plugin_dir=plugins
    )
    result = await YtDlpDownloader(staging, settings, Zipapp(), runner=runner).download(
        "OkWebm00001", JOB_DIR, _record
    )
    assert result.ext == "webm"
    pairs = dict(itertools.pairwise(seen[0]))
    assert pairs["--plugin-dirs"] == str(plugins)
    assert "youtubepot-bgutilhttp:base_url=http://pot-provider:4416" in seen[0]


async def test_the_downloader_loads_no_plugin_by_default(staging: LocalStagingStore) -> None:
    seen: list[list[str]] = []

    async def runner(args: list[str], env: dict[str, str]) -> Any:
        seen.append(args)
        return await ytdlp._open(args, env)

    # The default plugin directory does not exist here, and it does not matter.
    await YtDlpDownloader(staging, WorkerSettings(), Zipapp(), runner=runner).download(
        "OkWebm00001", JOB_DIR, _record
    )
    assert "--plugin-dirs" not in seen[0]
    assert not any("youtubepot" in a for a in seen[0])


async def test_a_missing_plugin_dir_fails_before_running_yt_dlp(
    staging: LocalStagingStore, tmp_path: Path
) -> None:
    async def runner(_args: list[str], _env: dict[str, str]) -> Any:
        raise AssertionError("yt-dlp must not run")

    settings = WorkerSettings(
        ytdlp_pot_provider_url="http://pot-provider:4416", ytdlp_plugin_dir=tmp_path / "none"
    )
    with pytest.raises(DownloadError) as caught:
        await YtDlpDownloader(staging, settings, Zipapp(), runner=runner).download(
            "OkWebm00001", JOB_DIR, _record
        )
    assert caught.value.code == WorkerErrorCode.INTERNAL_ERROR
    assert caught.value.retryable


# ---------------------------------------------------------------- no token in a log


@pytest.mark.parametrize(
    "template",
    [
        "[pot:bgutil:http] Generated POT: {}",
        'WARNING: response = {{"poToken": "{}"}}',
        "[debug] po_token={} used",
        "[debug] PO Token: {}",
    ],
)
def test_po_tokens_are_redacted(template: str) -> None:
    # A fresh stand-in token each run (base64url, like the real ones); never a literal.
    token = secrets.token_urlsafe(30)
    safe = redact(template.format(token))
    assert token not in safe
    assert "<redacted>" in safe


def test_provider_listings_are_kept() -> None:
    line = "[debug] [youtube] [pot] PO Token Providers: bgutil:http-2.0.2 (external)"
    assert redact(line) == line


# ---------------------------------------------------------------- the pins


def _dockerfile_arg(name: str) -> str:
    text = (REPO / "server" / "Dockerfile").read_text(encoding="utf-8")
    found = re.search(rf"^ARG {name}=(\S+)$", text, re.M)
    assert found, name
    return found.group(1)


def test_plugin_and_provider_image_are_pinned_to_one_version() -> None:
    """The plugin warns when it and the provider differ: both come from one upstream release."""
    version = _dockerfile_arg("BGUTIL_VERSION")
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert re.fullmatch(r"[0-9a-f]{64}", _dockerfile_arg("BGUTIL_PLUGIN_SHA256"))
    compose = (REPO / "server" / "compose.yaml").read_text(encoding="utf-8")
    images = re.findall(r"image: (\S*bgutil-ytdlp-pot-provider\S*)", compose)
    assert len(images) == 1
    # A version tag for humans, the digest for Docker: never a floating tag alone. The Deno
    # flavour: the Node one ships a Node.js with CVE-2026-111497 (Brotli decoder RCE).
    assert re.fullmatch(
        rf"docker\.io/brainicism/bgutil-ytdlp-pot-provider:{re.escape(version)}-deno@sha256:[0-9a-f]{{64}}",
        images[0],
    )


def _provider_block() -> str:
    compose = (REPO / "server" / "compose.yaml").read_text(encoding="utf-8")
    return compose.split("\n  pot-provider:\n", 1)[1].split("\n\n", 1)[0]


def test_the_provider_is_opt_in_hardened_and_never_on_the_apis_networks() -> None:
    block = _provider_block()
    assert "profiles: [pot]" in block
    assert "ports" not in block
    for hardening in (
        'user: "1993:1993"',
        "read_only: true",
        "cap_drop: [ALL]",
        "no-new-privileges:true",
        "mem_limit:",
        "cpus:",
        "pids_limit:",
    ):
        assert hardening in block
    networks = block.split("    networks:\n", 1)[1]
    assert re.findall(r"^      ([a-z]+):", networks, re.M) == ["egress", "pot"]
    # It listens only on its pinned address on `pot`, never on every interface.
    assert '"--host", "${UT_POT_PROVIDER_ADDRESS:-10.213.47.250}"' in block
    assert "0.0.0.0" not in block  # noqa: S104 - asserting it is absent
    # The worker's name for it exists only on `pot` (`pot-provider` may resolve on `egress`).
    assert "aliases: [bgutil]" in networks.split("      pot:", 1)[1]


def test_the_worker_is_the_only_other_member_of_the_pot_network() -> None:
    compose = (REPO / "server" / "compose.yaml").read_text(encoding="utf-8")
    services = compose.split("\nservices:\n", 1)[1].split("\nsecrets:\n", 1)[0]
    service = re.compile(r"^  ([a-z-]+):\n(.*?)(?=^  [a-z-]+:\n|\Z)", re.M | re.S)
    members = {
        name
        for name, body in service.findall(services)
        if re.search(r"\bpot\b(?!-)", body.split("networks:", 1)[-1])
    }
    assert members == {"worker", "pot-provider"}
    assert "UT_YTDLP_POT_PROVIDER_URL: ${UT_YTDLP_POT_PROVIDER_URL:-}" in services
    network = compose.split("\n  pot:\n", 1)[1]
    assert "internal: true" in network.split("\n\n", 1)[0]


# ---------------------------------------------------------------- the build-time check


def _check_plugin() -> Any:
    path = REPO / "server" / "docker" / "check_plugin.py"
    spec = importlib.util.spec_from_file_location("check_plugin", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _zip(path: Path, entries: dict[str, str]) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return str(path)


# The layout of upstream's release zip (2.0.2): two directories and three modules.
BASE = "yt_dlp_plugins/extractor/getpot_bgutil.py"
HTTP = "yt_dlp_plugins/extractor/getpot_bgutil_http.py"
SCRIPT = "yt_dlp_plugins/extractor/getpot_bgutil_script.py"
GOOD = {
    "yt_dlp_plugins/": "",
    "yt_dlp_plugins/extractor/": "",
    BASE: "x = 1\n__version__ = '2.0.2'\n",
    HTTP: "class BgUtilHTTPPTP: ...\n",
    SCRIPT: "class BgUtilScriptPTP: ...\n",
}


def test_the_build_check_keeps_only_the_http_provider(tmp_path: Path) -> None:
    out = tmp_path / "bgutil-http.zip"
    message = _check_plugin().check(_zip(tmp_path / "ok.zip", GOOD), "2.0.2", str(out))
    assert "bgutil plugin 2.0.2" in message
    with zipfile.ZipFile(out) as pruned:
        assert pruned.namelist() == ["yt_dlp_plugins/", "yt_dlp_plugins/extractor/", BASE, HTTP]
        assert pruned.read(HTTP) == GOOD[HTTP].encode()
        assert pruned.read(BASE) == GOOD[BASE].encode()
        # Fixed dates: the same input gives the same file.
        assert {info.date_time for info in pruned.infolist()} == {(2026, 1, 1, 0, 0, 0)}
    again = tmp_path / "again.zip"
    _check_plugin().check(_zip(tmp_path / "ok2.zip", GOOD), "2.0.2", str(again))
    assert again.read_bytes() == out.read_bytes()


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ({**GOOD, "evil.py": ""}, "evil.py"),
        ({**GOOD, "yt_dlp_plugins/../x.py": ""}, "yt_dlp_plugins/../x.py"),
        ({**GOOD, "yt_dlp_plugins/extractor/getpot_new.py": ""}, "getpot_new.py"),
        ({k: v for k, v in GOOD.items() if k != HTTP}, "getpot_bgutil_http.py"),
        ({k: v for k, v in GOOD.items() if k != SCRIPT}, "getpot_bgutil_script.py"),
        ({**GOOD, BASE: "__version__ = '2.0.1'\n"}, "2.0.1"),
        ({**GOOD, BASE: ""}, "version none"),
    ],
)
def test_the_build_check_refuses_anything_else(
    tmp_path: Path, entries: dict[str, str], message: str
) -> None:
    out = tmp_path / "out.zip"
    with pytest.raises(SystemExit, match=re.escape(message)):
        _check_plugin().check(_zip(tmp_path / "bad.zip", entries), "2.0.2", str(out))
    assert not out.exists()


def test_the_build_check_refuses_duplicate_entries(tmp_path: Path) -> None:
    path = tmp_path / "dup.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in GOOD.items():
            archive.writestr(name, text)
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(HTTP, "shadow\n")
    with pytest.raises(SystemExit, match="entries differ"):
        _check_plugin().check(str(path), "2.0.2", str(tmp_path / "out.zip"))


def test_the_build_check_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _check_plugin()
    with pytest.raises(SystemExit):
        module.main(["check_plugin.py"])
    out = tmp_path / "out.zip"
    module.main(["check_plugin.py", _zip(tmp_path / "ok.zip", GOOD), "2.0.2", str(out)])
    assert "HTTP provider only" in capsys.readouterr().out
    assert out.is_file()


@pytest.mark.parametrize("host", ["a;b", "a,b", "a%b"])
def test_the_last_guard_refuses_separators_whatever_the_host_check_says(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    monkeypatch.setattr(worker_settings, "_internal_host", lambda _host: host)
    with pytest.raises(ValueError, match="extractor arguments"):
        internal_base_url("http://pot-provider:4416")
