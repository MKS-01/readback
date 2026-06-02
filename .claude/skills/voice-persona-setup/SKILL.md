---
name: voice-persona-setup
description: Add a new Qwen3-TTS cloned voice and/or a new assistant persona to local-tts. Use when the user wants to clone a voice from an audio sample, tune how a cloned voice sounds (pitch/speed/style), or add/edit a persona (e.g. chef, professor). Covers prepping the reference clip, registering the clone in config.yaml, pitch-shifting for timbre, and seeding a persona in config.py.
---

# Voice clone + persona setup (local-tts)

Two independent tasks that often go together (a persona paired with its own voice).
Both are config-only and **require a server restart** to take effect. The UI voice
and persona pickers are **dynamic** (built from the `config` WS message), so no
frontend change is ever needed — new entries just appear in Settings.

Always confirm the missing details before acting: source audio path, desired
`name`, and (for personas) the personality/voice in one line. Then verify by
loading config (`python3 -c "from local_tts.config import Config; Config.load()"`).

---

## A. Add a cloned voice

Clones use the Qwen3-TTS **Base** checkpoint (`tts.qwen.base_model`); selecting one
reloads Base (~1.2 GB first use) and is slower than presets. Each clone shows in the
picker as `clone:<name>`.

### 1. Prep the reference clip
Re-encode ANY audio/video to the mono / 24 kHz / 16-bit PCM wav the Base model needs
(renaming an `.m4a`/`.opus` to `.wav` does NOT work — it must be re-encoded):

```bash
bash scripts/make_clone_voice.sh <input-file> <name>
# optional: -s <start_sec> -d <duration_sec> to trim a clean window; -l <lang>
```

- Output: `voice/<name>.wav` (the project `voice/` folder; `*.wav` is gitignored — clips stay local).
- A 10–15 s clean, single-speaker clip works well. The script prints a ready-to-paste config snippet.

### 2. Register it in `config.yaml`
Under `tts.qwen.clones`, add an entry. Use a **relative** `wav:` path (anchored to the
config file's dir → portable):

```yaml
      - name: <name>
        label: "<Picker Label>"
        wav: voice/<name>.wav      # relative to config.yaml's directory
        # ref_lang omitted → Whisper autodetects the clip's language & transcribes
        instruct: "<how it should speak>"   # see tuning below
        speed: 1.0                 # <1.0 slower, >1.0 faster
        temperature: 0.8           # lower = steadier, higher = more expressive
```

`ref_text` may be set explicitly (transcript of the clip in its OWN language);
omit it to auto-transcribe via Whisper on first use.

### 3. Tuning knobs (what changes what)
The **reference clip sets the timbre (WHO)**. The fields only shape delivery:
- **`instruct`** — *how* it speaks (the strongest lever short of changing the clip).
  e.g. `"a mature adult woman, calm warm and composed; scholarly gravitas, not
  high-pitched or childish"`, `"excited, fast"`, `"sad, soft"`.
- **`speed`** — pace. Useful range ~0.9 (slow) → 1.2 (fast). 0.92 read as "too slow"; 1.08 is brisk.
- **`temperature`** — ~0.7 steady/less sing-song, ~0.9 default, higher = more varied.

### 4. Can't fix timbre with instruct? Pitch-shift the clip → a NEW clone
If a clone sounds too childish/deep and `instruct` can't fix it (timbre lives in the
clip), derive a pitch-shifted variant and register it as a **separate** clone (keep
the original to A/B). ffmpeg has no `rubberband` here, so use `asetrate`+`atempo`
(shifts pitch, preserves duration):

```bash
# pitch DOWN n semitones: factor = 2^(-n/12). e.g. -3 st → factor 0.840896
ffmpeg -y -i voice/<name>.wav \
  -af "asetrate=24000*0.840896,aresample=24000,atempo=1.18921" \
  -ac 1 -ar 24000 -sample_fmt s16 voice/<name>_deep.wav
# for +n st (higher): factor = 2^(n/12); atempo = 1/factor
```

Then add a second clone entry pointing at `voice/<name>_deep.wav`. Note the clone
model doesn't always track the shift 1:1 — if it sounds artifact-y rather than just
lower, a different, naturally-more-suitable source recording is the cleaner fix.

---

## B. Add a persona

Personas are seeded in `_default_personas()` in `local_tts/config.py` (alongside
`default` / `concise` / `researcher` / `chef` / `professor`). `config.yaml`'s
`persona:` block only sets `active:` — adding to it is NOT required; the picker lists
every seeded persona.

Append a `Persona(...)` to the list:

```python
        Persona(
            name="<name>",
            system_prompt=(
                "<who they are and how they behave> "
                # Voice-friendly rules — replies are read aloud by TTS:
                "Since this is read aloud, avoid markdown, numbered lists, or special "
                "characters, and keep each answer to a few clear sentences unless asked "
                "to go deeper."
            ),
        ),
```

### Persona prompt tips (learned)
- **State the behavior concretely**, not just a label — a small local model
  (`nemotron-3-nano:4b`) follows specifics far better than vibes. (e.g. the chef
  persona: "lean vegetarian/egg by default, only meat when asked, vary across
  breakfast/snacks/mains/drinks" instead of just "Indian food".)
- **Want a guaranteed opening intro?** Make it MANDATORY with an example line and
  tell it not to repeat: *"ALWAYS begin your FIRST reply by introducing yourself in
  one sentence … For example: '…'. Do not reintroduce yourself on later turns."*
  Caveat: "first reply" is inferred from history (kept ~`ui.history_turns` turns),
  so on a very long session it may re-intro. For a byte-exact greeting every time,
  inject a scripted first line in code instead of relying on the prompt.
- **Always include the voice-friendly rules** above (no markdown/lists; few sentences)
  so TTS doesn't read out asterisks or run long.

---

## Verify & finish
```bash
python3 -c "
from local_tts.config import Config
c = Config.load()
print('personas:', [p.name for p in c.persona.personas])
print('clones  :', [(x.name, x.wav) for x in c.tts.qwen.clones])
"
```
- Confirm the new persona/clone appears and the clone `wav` path resolves & exists.
- Tell the user to **restart the server**, then Settings → Persona / voice to select.
- `voice/*.wav` is gitignored (local only); commit `config.yaml` / `config.py` if asked.

## Reference
- Qwen3-TTS voice clone: https://github.com/QwenLM/Qwen3-TTS#voice-clone
- Project specifics: see CLAUDE.md → "TTS — Qwen3-TTS" (cloning subsection) and "Persona".
