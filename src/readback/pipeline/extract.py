"""Article extraction: URL or local image -> clean {title, text} suitable for TTS.

For URLs: trafilatura (best-in-class boilerplate removal) pulls the main article
body out of arbitrary blog/news HTML, then lightly normalizes the text so the
TTS doesn't read URLs, citation markers, or stray markup aloud.

For images (.png/.jpg/.jpeg/.heic/.webp/.tiff/.bmp): the file is converted to
JPEG via sips (macOS built-in, no deps) if needed, then OCR'd via mlx-vlm using
`cfg.llm.model` — the SAME model that writes the summary. The default Qwen3.5 is
a VLM, so a second OCR model would just be a redundant download and a second
resident copy of the weights.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from readback.config import LLMConfig
    from readback.llm.client import LLMClient  # noqa: F811

log = logging.getLogger("readback.pipeline")


class ExtractError(Exception):
    """Fetch failed or no readable article text was found."""


@dataclass
class Article:
    title: str
    text: str
    url: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


# Light TTS-prep scrubbing on top of trafilatura's already-clean text.
_URL_RE = re.compile(r"https?://\S+")
_CITATION_RE = re.compile(r"\[\d+\]")          # "[1]", "[12]" reference markers
_MULTISPACE_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")


def _clean_for_tts(text: str) -> str:
    text = _URL_RE.sub("", text)
    text = _CITATION_RE.sub("", text)
    text = _MULTISPACE_RE.sub(" ", text)
    text = _MULTINEWLINE_RE.sub("\n\n", text)
    # Drop lines that are now empty/whitespace-only after scrubbing.
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln).strip()


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic", ".webp", ".tiff", ".tif", ".bmp"}
# Formats mlx-vlm can't load natively — convert to JPEG first via sips.
_NEEDS_CONVERT = {".heic", ".tiff", ".tif", ".bmp", ".webp"}


def _has_alpha(path: Path) -> bool:
    """True if the image carries an alpha channel (per macOS sips).

    ⚠ Load-bearing for transparent PNGs: mlx-vlm flattens alpha onto BLACK, so a
    page of black-on-transparent text arrives at the model as a solid black
    rectangle and OCR returns confident garbage rather than an error. Routing
    those through sips (which flattens onto white) is what makes them readable.
    """
    import subprocess

    try:
        r = subprocess.run(
            ["sips", "-g", "hasAlpha", str(path)], capture_output=True, text=True,
        )
        return "hasAlpha: yes" in r.stdout
    except Exception:
        log.debug("alpha check failed for %s", path, exc_info=True)
        return False

def _natural_sort_key(name: str):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", name)]


def _is_multi_page(source: str) -> bool:
    """True if source is a folder path or glob pattern (not a URL or single image)."""
    s = source.strip()
    if re.match(r"^https?://", s):
        return False
    if "*" in s or "?" in s:
        return True
    p = Path(s.replace("\\ ", " ")).expanduser()
    return p.is_dir()


def _collect_images(source: str) -> list[Path]:
    """Resolve a directory or glob pattern to a naturally-sorted list of image paths."""
    import glob as _glob

    s = source.strip().replace("\\ ", " ")
    if "*" in s or "?" in s:
        expanded = str(Path(s).expanduser()) if s.startswith("~") else s
        candidates = [Path(p) for p in _glob.glob(expanded)]
    else:
        candidates = list(Path(s).expanduser().iterdir())

    images = sorted(
        [c for c in candidates if c.suffix.lower() in _IMAGE_EXTS],
        key=lambda p: _natural_sort_key(p.name),
    )
    if not images:
        raise ExtractError(f"\U0001f5bc️ no images found in {source}")
    return images


def _is_image_path(source: str) -> bool:
    return Path(source).suffix.lower() in _IMAGE_EXTS


def _resolve_image_path(path: str) -> Path:
    """Unescape shell backslash-spaces only. U+202F stays as-is — macOS names files with it."""
    return Path(path.replace("\\ ", " ")).expanduser().resolve()


def _image_to_jpeg(src: Path) -> str:
    """Convert image to a temp JPEG using macOS sips (built-in, no extra deps).

    Returns the temp file's path — mlx-vlm takes paths, so the bytes never need
    to round-trip through memory. The caller owns the file and unlinks it.
    """
    import os
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    result = subprocess.run(
        ["sips", "-s", "format", "jpeg", str(src), "--out", tmp_path],
        capture_output=True,
    )
    if result.returncode != 0:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise ExtractError(
            f"\U0001f5bc️ couldn't convert {src.suffix.upper()} to JPEG: "
            f"{result.stderr.decode().strip()}"
        )
    return tmp_path


_vision_model = None
_vision_processor = None
_vision_config = None
_vision_loaded_id: str | None = None


def _ensure_vision_model(model_id: str):
    """Lazily load the mlx-vlm vision model, reusing across calls."""
    global _vision_model, _vision_processor, _vision_config, _vision_loaded_id
    if _vision_model is not None and _vision_loaded_id == model_id:
        return
    from mlx_vlm import load as vlm_load
    from mlx_vlm.utils import load_config

    if _vision_model is not None:
        log.info("unloading vision model %s", _vision_loaded_id)
        del _vision_model, _vision_processor
        _vision_model = None
        _vision_processor = None
    log.info("loading vision model %s", model_id)
    _vision_model, _vision_processor = vlm_load(model_id)
    _vision_config = load_config(model_id)
    _vision_loaded_id = model_id
    log.info("vision model ready: %s", model_id)


def _ocr_via_mlx(path: str, model_id: str) -> str:
    """Resolve, convert if needed, then OCR an image via mlx-vlm.

    `model_id` is the summary LLM (`cfg.llm.model`) — the default Qwen3.5 is a
    VLM, so there's no separate OCR model to configure. A text-only model here
    fails to load and surfaces as an ExtractError.
    """
    from mlx_vlm import generate as vlm_generate
    from mlx_vlm.prompt_utils import apply_chat_template

    abs_path = _resolve_image_path(path)
    if not abs_path.exists():
        raise ExtractError(f"\U0001f5bc️ image not found: {abs_path}")

    log.info("OCR %s via %s", abs_path.name, model_id)

    suffix = abs_path.suffix.lower()
    if suffix in _NEEDS_CONVERT or _has_alpha(abs_path):
        log.info("converting %s to JPEG for OCR", suffix)
        image_path = _image_to_jpeg(abs_path)
    else:
        image_path = str(abs_path)

    try:
        _ensure_vision_model(model_id)
        prompt_text = (
            "Extract all text from this image verbatim. "
            "Preserve line breaks and structure. Output only the text, no commentary."
        )
        formatted_prompt = apply_chat_template(
            _vision_processor, _vision_config, prompt_text, num_images=1,
        )
        result = vlm_generate(
            _vision_model, _vision_processor, formatted_prompt,
            [image_path], max_tokens=4096, temperature=0.0, verbose=False,
        )
    except Exception as e:
        raise ExtractError(f"\U0001f916 OCR failed ({model_id}): {e}") from e
    finally:
        if image_path != str(abs_path):
            import os
            try:
                os.unlink(image_path)
            except OSError:
                pass

    from readback.llm.client import strip_think
    # mlx-vlm's generate() returns a GenerationResult (has .text) in current
    # releases; older versions returned the raw string. Handle both.
    raw = getattr(result, "text", result)
    text = strip_think(str(raw) if raw is not None else "").strip()
    if not text:
        raise ExtractError("\U0001f5bc️ no text found in the image")
    return text


def _book_title_from_text(text: str, llm_cfg: "LLMConfig", llm: "LLMClient | None" = None) -> str:
    """Distill a book page's chapter/topic from its opening lines. Falls back to 'Book'.

    Books usually carry the chapter heading or topic in the first lines, so we feed
    just those — the book reading tone then opens the summary by naming it.
    """
    from readback.llm.client import LLMClient
    head = "\n".join(text.strip().splitlines()[:3])[:600]
    try:
        client = llm or LLMClient(llm_cfg)
        raw = client.oneshot(
            "You identify the chapter or topic of a book page from its opening lines. "
            "Reply with ONLY the chapter name or topic, at most 8 words. No quotes, no commentary.",
            f"Opening lines:\n\n{head}",
        )
        title = raw.strip().strip('"').strip("'").strip()
        return title or "Book"
    except Exception:
        log.debug("book title generation failed, using fallback", exc_info=True)
        return "Book"


def classify_source(source: str) -> str:
    """Reading-tone source kind: 'book' for an image / folder / glob, else 'article'.

    Images are (mostly) book scans in this tool, so any local image path or
    multi-page folder/glob reads as a book; URLs read as articles.
    """
    s = (source or "").strip()
    if _is_multi_page(s) or _is_image_path(s):
        return "book"
    return "article"


def fetch_multi_page(
    source: str,
    llm_cfg: "LLMConfig",
    progress_cb=None,
    llm: "LLMClient | None" = None,
) -> Article:
    """OCR every image in a folder/glob and stitch them into one continuous Article.

    Pages are read in natural filename order and concatenated as a single flowing
    document — a scanned page is a *page*, not a chapter, so there are no synthetic
    chapter headers. The result feeds the normal full/summary pipeline unchanged
    (the caller summarizes via `summarize_article` just like a URL article).
    `progress_cb(page_index, total)` fires before each page is OCR'd.
    """
    images = _collect_images(source)
    total = len(images)
    log.info("multi-page OCR via %s (%d pages)", llm_cfg.model, total)

    pages: list[str] = []
    for i, img_path in enumerate(images):
        if progress_cb:
            progress_cb(i, total)
        log.info("OCR page %d/%d: %s", i + 1, total, img_path.name)
        try:
            pages.append(_ocr_via_mlx(str(img_path), llm_cfg.model))
        except ExtractError:
            log.warning("skipping page %d (%s): OCR failed", i + 1, img_path.name, exc_info=True)

    if progress_cb:
        progress_cb(total, total)

    if not pages:
        raise ExtractError("\U0001f5bc️ no text found in any of the pages")

    full_text = " ".join(p.strip() for p in pages if p.strip())
    title = _book_title_from_text(pages[0], llm_cfg, llm=llm)

    article = Article(title=title, text=_clean_for_tts(full_text), url=source)
    log.info("multi-page: %d pages, %d words, title=%r", len(pages), article.word_count, title)
    return article


def _fallback_title(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"[-_]+", " ", tail).strip()
    return tail or "Article"


# A realistic browser UA -- trafilatura's default UA is blocked by many sites.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _download(url: str) -> str:
    """Fetch raw HTML, trying trafilatura first then a browser-UA urllib fallback
    (many sites 403 trafilatura's default agent)."""
    import trafilatura

    html = trafilatura.fetch_url(url)
    if html:
        return html
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 (user-supplied URL)
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def fetch_article(
    source: str,
    llm_cfg: "LLMConfig | None" = None,
    llm: "LLMClient | None" = None,
) -> Article:
    """Fetch `source` and return the extracted, TTS-ready article.

    `source` may be a URL (http/https) or a local image path. `llm_cfg.model` is
    used for both the OCR pass (image sources) and title generation. Raises
    ExtractError on a failed fetch or when no article text is found.
    """
    source = (source or "").strip()
    if not source:
        raise ExtractError("no source provided")

    # --- local image (a book page, in this tool) ---
    if _is_image_path(source):
        if llm_cfg is None:
            raise ExtractError("\U0001f5bc️ image OCR requires an LLM config")
        text = _ocr_via_mlx(source, llm_cfg.model)
        title = _book_title_from_text(text, llm_cfg, llm=llm)
        article = Article(title=title, text=_clean_for_tts(text), url=source)
        log.info("OCR extracted %r (%d words) from %s", title, article.word_count, source)
        return article

    # --- URL ---
    import trafilatura

    url = source
    if not re.match(r"^https?://", url):
        url = "https://" + url

    try:
        downloaded = _download(url)
    except Exception as e:
        raise ExtractError(f"could not fetch the page at {url}: {e}") from e
    if not downloaded:
        raise ExtractError(f"could not fetch the page at {url}")

    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or not text.strip():
        raise ExtractError("no readable article text found at that URL")

    title = ""
    try:
        md = trafilatura.extract_metadata(downloaded)
        if md and md.title:
            title = md.title
    except Exception:
        pass
    title = (title or _fallback_title(url)).strip()

    article = Article(title=title, text=_clean_for_tts(text), url=url)
    log.info("extracted %r (%d words) from %s", title, article.word_count, url)
    return article
