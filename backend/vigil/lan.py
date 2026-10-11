"""Reaching Vigil from a phone on the same Wi-Fi.

Phone browsers only allow camera access on HTTPS pages (localhost is the exception, and on a phone localhost is
the phone itself). So Vigil also listens on the LAN with HTTPS, using a self-signed certificate it makes once.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import socket

from .config import settings


def lan_ip() -> str | None:
    """This computer's address on the Wi-Fi / Ethernet (not a VPN tunnel); no packets are sent."""
    import subprocess
    import sys

    if sys.platform == "darwin":
        for dev in ("en0", "en1"):  # Wi-Fi / Ethernet; the default route may be a VPN
            try:
                ip = subprocess.run(["ipconfig", "getifaddr", dev], capture_output=True, text=True, timeout=2).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                ip = ""
            if ip:
                return ip
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def lan_url() -> str | None:
    ip = lan_ip()
    return f"https://{ip}:{settings.lan_https_port}" if ip and settings.lan_https_port else None


def ensure_cert() -> tuple[str, str]:
    """A self-signed certificate for this machine's LAN address, remade when the address changes."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    d = settings.data_dir / "tls"
    d.mkdir(parents=True, exist_ok=True)
    cert, key, stamp = d / "lan.crt", d / "lan.key", d / "lan.ip"
    ip = lan_ip() or "127.0.0.1"
    if cert.exists() and key.exists() and stamp.exists() and stamp.read_text() == ip:
        return str(cert), str(key)
    k = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Vigil on this computer")])
    host = socket.gethostname()
    san = [x509.DNSName("localhost"), x509.DNSName(host), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
           x509.IPAddress(ipaddress.ip_address(ip))]
    now = dt.datetime.now(dt.timezone.utc)
    c = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
         .not_valid_after(now + dt.timedelta(days=397))
         .add_extension(x509.SubjectAlternativeName(san), critical=False)
         .sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    key.chmod(0o600)
    cert.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    stamp.write_text(ip)
    return str(cert), str(key)
