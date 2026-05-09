import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="local-tts — local voice conversation (web UI)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--model", default=None, help="Override Ollama model")
    parser.add_argument("--config", dest="config_path", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()

    import uvicorn
    from local_tts.config import Config
    from local_tts.web.server import create_app

    cfg = Config.load(args.config_path)
    if args.model:
        cfg.ollama.model = args.model

    app = create_app(cfg)
    print(f"\n  ▸ open http://{args.host}:{args.port} in your browser\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
