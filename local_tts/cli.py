from pathlib import Path
from typing import Optional

import click


@click.group()
def cli():
    """local-tts — Sesame-like local voice conversation CLI."""


@cli.command()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=Path("config.yaml"))
@click.option("--model", default=None, help="Override Ollama model")
@click.option("--text-mode", is_flag=True, help="Start in text input mode")
def run(config_path: Path, model: Optional[str], text_mode: bool):
    """Start the voice conversation app."""
    from local_tts.config import Config
    from local_tts.app import ConversationApp

    cfg = Config.load(config_path)
    if model:
        cfg.ollama.model = model
    if text_mode:
        cfg.ui.default_mode = "text"

    app = ConversationApp(cfg)
    app.start()


@cli.command("list-devices")
def list_devices():
    """List audio input/output devices and their indices."""
    import sounddevice as sd

    click.echo(sd.query_devices())


@cli.command("list-models")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=Path("config.yaml"))
def list_models(config_path: Path):
    """List available Ollama models on the configured host."""
    from local_tts.config import Config
    from local_tts.llm.client import LLMClient

    cfg = Config.load(config_path)
    client = LLMClient(cfg.ollama)
    models = client.list_models()
    if not models:
        click.echo(f"No models found at {cfg.ollama.host}. Is Ollama running?")
        return
    click.echo(f"Models on {cfg.ollama.host}:")
    for m in models:
        marker = " *" if m == cfg.ollama.model else ""
        click.echo(f"  {m}{marker}")


@cli.command("download-models")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=Path("config.yaml"))
def download_models(config_path: Path):
    """Pre-download Whisper and CSM model weights."""
    from local_tts.config import Config

    cfg = Config.load(config_path)

    click.echo(f"Downloading Whisper {cfg.whisper.model}...")
    from faster_whisper import WhisperModel

    WhisperModel(cfg.whisper.model, device="cpu", compute_type=cfg.whisper.compute_type)
    click.echo("✓ Whisper ready")

    click.echo("Downloading CSM-1B (~6.2GB)...")
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id="sesame/csm-1b")
    snapshot_download(repo_id="meta-llama/Llama-3.2-1B")
    click.echo("✓ CSM-1B ready")
    click.echo("\nAll models downloaded. Run: local-tts run")


@cli.command("test-tts")
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=Path("config.yaml"))
@click.argument("text", default="Hello, this is Sesame running locally on Apple Silicon.")
def test_tts(config_path: Path, text: str):
    """Quick TTS smoke test — synthesize a sentence and play it."""
    import sounddevice as sd

    from local_tts.config import Config
    from local_tts.tts.synthesizer import Synthesizer

    cfg = Config.load(config_path)
    synth = Synthesizer(cfg.csm)
    click.echo("Loading CSM model...")
    synth.load()
    click.echo(f"Device: {synth.device}, Sample rate: {synth.sample_rate}")
    click.echo(f"Synthesizing: {text!r}")
    audio = synth.synthesize(text)
    click.echo(f"Generated {len(audio)} samples ({len(audio)/synth.sample_rate:.2f}s). Playing...")
    sd.play(audio, samplerate=synth.sample_rate)
    sd.wait()
    click.echo("Done.")


if __name__ == "__main__":
    cli()
