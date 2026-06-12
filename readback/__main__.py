import argparse
import socket
from pathlib import Path


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(
        description="readback — offline article reader (URL → audio via CLI)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--model", default=None, help="Override Ollama model")
    parser.add_argument("--config", dest="config_path", type=Path, default=Path("config.yaml"))

    args = parser.parse_args()

    import uvicorn
    from readback.config import Config
    from readback.web.server import create_app

    cfg = Config.load(args.config_path)
    if args.model:
        cfg.ollama.model = args.model

    local_url   = f"http://127.0.0.1:{args.port}"
    network_url = f"http://{_local_ip()}:{args.port}" if args.host == "0.0.0.0" else None

    print()
    print(f"  ▸ Local:   {local_url}")
    if network_url:
        print(f"  ▸ Network: {network_url}")
    print()

    app = create_app(cfg)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
