"""ONVIF WS-Discovery probe plus RTSP URL templates for common camera brands."""

from __future__ import annotations

import re
import socket
import time
import uuid
from urllib.parse import unquote, urlparse

PROBE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
    'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
    'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    "<e:Header><w:MessageID>uuid:{mid}</w:MessageID>"
    '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
    '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
    "</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>"
)

# Substream paths keep decode cost low; recordings use the same frames.
RTSP_TEMPLATES = [
    {"brand": "Reolink", "url": "rtsp://{user}:{password}@{ip}:554/h264Preview_01_sub"},
    {"brand": "Tapo (TP-Link)", "url": "rtsp://{user}:{password}@{ip}:554/stream2"},
    {"brand": "Hikvision / Annke", "url": "rtsp://{user}:{password}@{ip}:554/Streaming/Channels/102"},
    {"brand": "Dahua / Amcrest / Lorex", "url": "rtsp://{user}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=1"},
    {"brand": "Axis", "url": "rtsp://{user}:{password}@{ip}/axis-media/media.amp?resolution=640x360"},
    {"brand": "Hanwha (Wisenet)", "url": "rtsp://{user}:{password}@{ip}:554/profile2/media.smp"},
    {"brand": "UniFi Protect", "url": "rtsps://{ip}:7441/{stream_token}?enableSrtp"},
    {"brand": "Eufy (RTSP enabled)", "url": "rtsp://{user}:{password}@{ip}:554/live0"},
    {"brand": "go2rtc / MediaMTX restream", "url": "rtsp://{ip}:8554/{stream_name}"},
]


def discover(timeout: float = 3.0) -> list[dict]:
    """Multicast a WS-Discovery Probe and collect ONVIF devices that answer."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    found: dict[str, dict] = {}
    try:
        sock.sendto(PROBE.format(mid=uuid.uuid4()).encode(), ("239.255.255.250", 3702))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (ip, _) = sock.recvfrom(65535)
            except socket.timeout:
                continue
            text = data.decode(errors="ignore")
            xaddrs = re.findall(r"<[^>]*XAddrs>([^<]+)</", text)
            scopes = " ".join(re.findall(r"<[^>]*Scopes>([^<]+)</", text)).split()
            name = _scope(scopes, "name")
            hardware = _scope(scopes, "hardware")
            addrs = xaddrs[0].split() if xaddrs else []
            host = urlparse(addrs[0]).hostname if addrs else ip
            found[host or ip] = {
                "ip": host or ip,
                "name": name or hardware or "ONVIF camera",
                "hardware": hardware,
                "xaddrs": addrs,
            }
    except OSError:
        pass
    finally:
        sock.close()
    return list(found.values())


def _scope(scopes: list[str], key: str) -> str:
    for s in scopes:
        m = re.match(rf"onvif://www\.onvif\.org/{key}/(.+)", s)
        if m:
            return unquote(m.group(1)).replace("_", " ")
    return ""
