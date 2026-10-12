# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""IP address helpers shared by the admin allowlist, the trusted-proxy rule and `/readyz`."""

import ipaddress

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

LOOPBACK: tuple[IpNetwork, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def parse_networks(text: str) -> tuple[IpNetwork, ...]:
    """Comma-separated CIDRs (host bits allowed); an empty text is no network."""
    return tuple(
        ipaddress.ip_network(part.strip(), strict=False) for part in text.split(",") if part.strip()
    )


def parse_ip(host: str | None) -> IpAddress | None:
    """The address in `host`, or None for hostnames, missing values and garbage. A zone id
    (`fe80::1%eth0`) is dropped; IPv4-mapped IPv6 addresses count as IPv4."""
    if not host:
        return None
    try:
        address = ipaddress.ip_address(host.strip().split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(address, "ipv4_mapped", None)
    return mapped or address


def in_networks(host: str | None, networks: tuple[IpNetwork, ...]) -> bool:
    """True when `host` is an IP address inside one of `networks`."""
    address = parse_ip(host)
    if address is None:
        return False
    return any(address.version == net.version and address in net for net in networks)
