import argparse
import ipaddress
import json
import socket
from pathlib import Path
from typing import Optional


def _local_ip() -> str:
    """Best-effort: detect the LAN IP this machine uses to reach the internet."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _ensure_cert(cert_path: Path, key_path: Path, ip: str) -> None:
    """Generate a self-signed cert+key for `ip`. Skips if files exist for the same IP."""
    meta_path = cert_path.with_suffix(".meta.json")
    if cert_path.exists() and key_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("ip") == ip:
            return

    try:
        import datetime
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise SystemExit("\n  cryptography not found — run: pip install cryptography\n")

    print(f"  ▸ Generating self-signed TLS cert for {ip} …", flush=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ip)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=825))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.IPv4Address(ip)),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    meta_path.write_text(json.dumps({"ip": ip}))


def _fingerprint(cert_path: Path) -> str:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        fp = cert.fingerprint(hashes.SHA256())
        return ":".join(f"{b:02X}" for b in fp)
    except Exception:
        return ""


def main():
    parser = argparse.ArgumentParser(
        description="readback — offline article reader (URL → audio, web UI)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--model", default=None, help="Override Ollama model")
    parser.add_argument("--config", dest="config_path", type=Path, default=Path("config.yaml"))

    ssl_grp = parser.add_mutually_exclusive_group()
    ssl_grp.add_argument(
        "--auto-cert", action="store_true",
        help="Auto-generate a self-signed TLS cert for cross-device (LAN) access",
    )
    ssl_grp.add_argument("--cert", metavar="FILE", type=Path, help="TLS certificate (PEM)")
    parser.add_argument("--key", metavar="FILE", type=Path, help="TLS private key (PEM) — required with --cert")

    args = parser.parse_args()

    if args.cert and not args.key:
        parser.error("--cert requires --key")
    if args.key and not args.cert:
        parser.error("--key requires --cert")

    import uvicorn
    from readback.config import Config
    from readback.web.server import create_app

    cfg = Config.load(args.config_path)
    if args.model:
        cfg.ollama.model = args.model

    # ── SSL setup ──────────────────────────────────────────────────────────
    ssl_certfile: Optional[str] = None
    ssl_keyfile: Optional[str] = None
    cert_path_for_download: Optional[Path] = None
    lan_ip = _local_ip()
    scheme = "http"

    if args.auto_cert:
        cert_dir = Path.home() / ".readback" / "certs"
        cert_path = cert_dir / "cert.pem"
        key_path  = cert_dir / "key.pem"
        _ensure_cert(cert_path, key_path, lan_ip)
        ssl_certfile = str(cert_path)
        ssl_keyfile  = str(key_path)
        cert_path_for_download = cert_path
        scheme = "https"
    elif args.cert:
        ssl_certfile = str(args.cert)
        ssl_keyfile  = str(args.key)
        cert_path_for_download = args.cert
        scheme = "https"

    # ── Startup banner ─────────────────────────────────────────────────────
    local_url   = f"{scheme}://127.0.0.1:{args.port}"
    network_url = f"{scheme}://{lan_ip}:{args.port}" if args.host == "0.0.0.0" else None

    print()
    print(f"  ▸ Local:   {local_url}")
    if network_url:
        print(f"  ▸ Network: {network_url}")

    if scheme == "https" and args.host == "127.0.0.1":
        print()
        print("  ⚠  HTTPS is on but host is 127.0.0.1")
        print("     Pass --host 0.0.0.0 to make the server reachable on your network")

    if args.auto_cert and cert_path_for_download:
        fp = _fingerprint(cert_path_for_download)
        if fp:
            print()
            print("  ▸ TLS fingerprint — trust this once in your browser:")
            print(f"    {fp}")
        if network_url:
            print()
            print(f"  ▸ To trust on other devices, open on that device:")
            print(f"    {network_url}/cert.pem")
            print("    iOS:     Settings → General → VPN & Device Management → install → Certificate Trust Settings → enable")
            print("    Android: open link → install as CA certificate (Settings › Security › Install from storage)")
            print("    macOS:   open link → double-click downloaded file → Keychain → set to Always Trust")

    print()

    app = create_app(cfg, cert_path=cert_path_for_download)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        ssl_certfile=ssl_certfile,
        ssl_keyfile=ssl_keyfile,
    )


if __name__ == "__main__":
    main()
