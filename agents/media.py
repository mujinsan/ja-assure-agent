"""Media generation: prompt expansion, image chain, video render, safe uploads.

The image chain is (a) a Gemini image model, (b) a branded Pillow card, so the
demo always produces something even with no quota. Nothing here prints keys.
"""
import asyncio, io, os, re, uuid
from pathlib import Path

from agents.llm import generate_json
from config import BRANDS

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "media"))
IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")

# platform -> (width, height). Instagram 1:1, LinkedIn 1.91:1, video 9:16.
ASPECT = {"instagram": (1080, 1080), "linkedin": (1200, 628), "x": (1200, 628)}
VIDEO_SIZE = (1080, 1920)

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_VIDEO_BYTES = 25 * 1024 * 1024

# muted accents so generated cards stay inside the app's palette
BRAND_COLOUR = {"Jade": "#2E7D6B", "Jaguar Transit": "#3C5A82",
                "DoctorShield": "#3F7C86"}

SAFETY = ("Hard constraints: no logos or brand marks; no readable text, letters "
          "or numbers anywhere in the image; no identifiable real people; "
          "nothing implying guaranteed protection, payouts or outcomes.")


def _dir():
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_DIR


def size_for(platform, video=False):
    if video:
        return VIDEO_SIZE
    return ASPECT.get((platform or "").strip().lower(), (1200, 628))


def aspect_label(platform, video=False):
    if video:
        return "9:16"
    return {"instagram": "1:1", "linkedin": "1.91:1", "x": "1.91:1"}.get(
        (platform or "").strip().lower(), "1.91:1")


# --- prompt expansion --------------------------------------------------------

def expand_prompt(idea, asset, video=False):
    """Turn a rough or detailed idea into a full generation prompt.

    Keeps everything the user specified and only fills the gaps. Falls back to
    a locally assembled prompt if the LLM chain is unavailable.
    """
    brand = asset.get("brand") or ""
    b = BRANDS.get(brand, {})
    platform = asset.get("platform") or ""
    ratio = aspect_label(platform, video)
    caption = (asset.get("content") or "")[:600]
    idea = (idea or "").strip()

    system = ("You write prompts for an image generation model, for a regulated "
              "insurance marketer. You never invent brand marks or text.")
    prompt = f"""Expand this into ONE detailed image generation prompt.

User's idea: {idea or "(none given - infer from the caption)"}
Brand: {brand}. Niche: {b.get('niche','')}. Voice: {b.get('voice','')}.
Audience: {b.get('audience','')}.
Platform: {platform} at aspect ratio {ratio}.
Post caption: \"\"\"{caption}\"\"\"

Rules:
- Keep EVERY detail the user specified, word for word where possible.
- Only fill in what is missing: subject, composition, lighting, colour palette
  in the brand's style, and mood.
- Do not add logos, brand marks, words, letters or numbers.
- End the prompt with the safety constraints verbatim.

{SAFETY}

Return JSON: {{"prompt": "..."}}"""

    out = generate_json(prompt, system, mock={})
    expanded = (out or {}).get("prompt", "").strip()
    if not expanded:
        # local fallback so the box is never empty
        expanded = (f"{idea or 'Abstract professional visual'} - "
                    f"{b.get('niche','insurance')} for {b.get('audience','professionals')}. "
                    f"Composition suited to {ratio}. Calm, premium, {b.get('voice','professional')}. "
                    f"Muted silver and blue-grey palette, soft directional lighting. {SAFETY}")
    if "no logos" not in expanded.lower():
        expanded = f"{expanded}\n\n{SAFETY}"
    return expanded


# --- image chain -------------------------------------------------------------

def generate_image(prompt, asset, version, video=False):
    """(path, provider). Tries the Gemini image model, then a Pillow card."""
    size = size_for(asset.get("platform"), video)
    out = _dir() / f"{asset['id']}_v{version}.png"
    try:
        data = _gemini_image(prompt)
        _save_bytes_as_png(data, out, size)
        return str(out), f"gemini:{IMAGE_MODEL}"
    except Exception as e:
        print(f"[media] image model unavailable ({e}); using branded card")
        _pillow_card(asset, out, size)
        return str(out), "pillow-card"


def _gemini_image(prompt):
    """Raw image bytes from the Gemini image model, or raise."""
    from agents.llm import _get, live
    if not live():
        raise RuntimeError("no GEMINI_API_KEY")
    resp = _get().models.generate_content(model=IMAGE_MODEL, contents=prompt)
    for cand in (resp.candidates or []):
        for part in (getattr(cand.content, "parts", None) or []):
            blob = getattr(part, "inline_data", None)
            if blob and getattr(blob, "data", None):
                return blob.data
    raise RuntimeError("image model returned no image data")


def _save_bytes_as_png(data, out, size):
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img = _cover(img, size)
    img.save(out, "PNG")


def _cover(img, size):
    """Scale-and-crop to the target aspect without distortion."""
    from PIL import Image
    tw, th = size
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    img = img.resize((max(1, int(sw * scale)), max(1, int(sh * scale))), Image.LANCZOS)
    w, h = img.size
    return img.crop(((w - tw) // 2, (h - th) // 2, (w - tw) // 2 + tw, (h - th) // 2 + th))


def hook_of(asset, limit=110):
    """First sentence of the caption, for the fallback card."""
    text = " ".join((asset.get("content") or "").split())
    first = re.split(r"(?<=[.!?])\s", text)[0] if text else ""
    first = first or text
    return first if len(first) <= limit else first[:limit - 1].rstrip() + "…"


def _font(size):
    from PIL import ImageFont
    for name in ("seguisb.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _pillow_card(asset, out, size):
    """Branded card: hook, brand name, brand colour, no external assets."""
    from PIL import Image, ImageDraw
    w, h = size
    accent = BRAND_COLOUR.get(asset.get("brand"), "#3C5A82")
    img = Image.new("RGB", (w, h), "#0a0a0c")
    d = ImageDraw.Draw(img)

    # soft accent band and a rule, kept abstract - no logos, no numbers
    d.rectangle([0, 0, w, int(h * 0.012)], fill=accent)
    pad = int(w * 0.07)
    d.line([pad, int(h * 0.30), pad + int(w * 0.10), int(h * 0.30)], fill=accent, width=4)

    body = _font(max(20, int(h * 0.062)))
    small = _font(max(13, int(h * 0.030)))

    # wrap the hook by measured width rather than a character guess
    words, lines, cur = hook_of(asset).split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=body) <= w - 2 * pad:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)

    y = int(h * 0.36)
    for line in lines[:5]:
        d.text((pad, y), line, font=body, fill="#f2f2f5")
        y += int(body.size * 1.32)

    d.text((pad, h - int(h * 0.11)), (asset.get("brand") or "").upper(),
           font=small, fill=accent)
    img.save(out, "PNG")


# --- video -------------------------------------------------------------------

def video_script(idea, asset):
    """{'voiceover': 2-3 sentences, 'scene': description}."""
    b = BRANDS.get(asset.get("brand") or "", {})
    out = generate_json(
        f"""Write a short social video for {asset.get('brand')}.
Idea: {(idea or '').strip() or '(infer from the caption)'}
Niche: {b.get('niche','')}. Voice: {b.get('voice','')}. Audience: {b.get('audience','')}.
Caption: \"\"\"{(asset.get('content') or '')[:500]}\"\"\"

Give a 2-3 sentence spoken voiceover (no guarantees, no superlatives, mention
that terms apply if coverage is discussed) and one scene description for a
vertical 9:16 still.

Return JSON: {{"voiceover": "...", "scene": "..."}}""",
        "You write compliant short-form video briefs for an insurance marketer.",
        mock={})
    vo = (out or {}).get("voiceover", "").strip()
    scene = (out or {}).get("scene", "").strip()
    if not vo:
        vo = (f"{hook_of(asset)} {b.get('niche','Cover').capitalize()} "
              f"built around your practice. Terms and conditions apply.")
    if not scene:
        scene = f"Calm abstract vertical visual for {b.get('niche','insurance')}"
    return {"voiceover": vo, "scene": scene}


def _tts(text, path):
    """edge-tts to an mp3. Raises if unavailable."""
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, "en-GB-SoniaNeural").save(str(path))

    asyncio.run(go())
    if not Path(path).exists() or Path(path).stat().st_size == 0:
        raise RuntimeError("tts produced no audio")


def _caption_onto(img_path, text, out_path):
    """Burn captions with Pillow, avoiding MoviePy's TextClip font lookup."""
    from PIL import Image, ImageDraw
    img = Image.open(img_path).convert("RGB")
    w, h = img.size
    d = ImageDraw.Draw(img, "RGBA")
    font = _font(max(28, int(h * 0.030)))
    pad = int(w * 0.07)

    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=font) <= w - 2 * pad:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    lines = lines[:6]

    line_h = int(font.size * 1.35)
    block = line_h * len(lines) + int(h * 0.04)
    top = h - block - int(h * 0.08)
    d.rectangle([0, top - int(h * 0.02), w, top + block], fill=(10, 10, 12, 190))
    y = top
    for line in lines:
        d.text((pad, y), line, font=font, fill="#f2f2f5")
        y += line_h
    img.save(out_path, "PNG")
    return out_path


def generate_video(idea, asset, version, seconds=10):
    """(path, provider, script). Raises on failure; callers show 'Video unavailable'."""
    script = video_script(idea, asset)
    prompt = expand_prompt(f"{idea} {script['scene']}".strip(), asset, video=True)

    still, img_provider = generate_image(prompt, asset, f"{version}_scene", video=True)
    framed = _caption_onto(still, script["voiceover"], _dir() / f"{asset['id']}_v{version}_frame.png")

    audio_path = _dir() / f"{asset['id']}_v{version}.mp3"
    have_audio = True
    try:
        _tts(script["voiceover"], audio_path)
    except Exception as e:
        print(f"[media] tts unavailable ({e}); rendering silent")
        have_audio = False

    from moviepy import AudioFileClip, ImageClip
    out = _dir() / f"{asset['id']}_v{version}.mp4"
    audio = AudioFileClip(str(audio_path)) if have_audio else None
    duration = max(4.0, min(20.0, audio.duration + 0.6)) if audio else float(seconds)

    clip = ImageClip(str(framed)).with_duration(duration).resized(VIDEO_SIZE)
    if audio:
        clip = clip.with_audio(audio)
    clip.write_videofile(str(out), fps=24, codec="libx264",
                         audio_codec="aac" if audio else None,
                         logger=None)
    clip.close()
    if audio:
        audio.close()
    return str(out), img_provider, script


# --- uploads -----------------------------------------------------------------

SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image"),
    (b"\xff\xd8\xff", "jpg", "image"),
)


def sniff(data):
    """(ext, kind) from the header bytes, or (None, None). Extension is ignored."""
    for sig, ext, kind in SIGNATURES:
        if data.startswith(sig):
            return ext, kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand[:3] in (b"iso", b"mp4", b"avc", b"M4V") or brand in (b"mp42", b"isom", b"dash"):
            return "mp4", "video"
    return None, None


def save_upload(data, asset_id, version):
    """Validate by header, strip image metadata, save under a generated name.

    Returns (path, kind). Raises ValueError on an unsupported or oversized file.
    """
    ext, kind = sniff(data or b"")
    if not ext:
        raise ValueError("unsupported file type (header did not match png/jpg/webp/mp4)")
    cap = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
    if len(data) > cap:
        raise ValueError(f"{kind} too large: {len(data)/1048576:.1f} MB > {cap//1048576} MB")

    stem = f"{asset_id}_v{version}_up{uuid.uuid4().hex[:6]}"
    if kind == "image":
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
        clean = Image.new(img.mode, img.size)
        clean.putdata(list(img.getdata()))          # pixels only: no EXIF carried over
        out = _dir() / f"{stem}.png"
        clean.save(out, "PNG")
        return str(out), kind

    out = _dir() / f"{stem}.mp4"
    with open(out, "wb") as fh:
        fh.write(data)
    return str(out), kind
