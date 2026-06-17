---
name: drive-cli
description: Drive the readback CLI interactively via tmux to smoke-test player controls, screen transitions, and key bindings. Use after any change to src/cli/ — player, input, library, or key handling — when you need to verify the real app, not just the build. Covers launch, playback, pause/resume, seek, library nav, and teardown.
---

# drive-cli — interactive CLI smoke test via tmux

Launch the Ink CLI in a tmux session, drive it with `send-keys`, and read
results with `capture-pane`. This is the only way to test key-driven behavior
(player controls, screen transitions) — Ink needs a TTY, so direct `Bun.spawn`
from the agent shell won't work.

## Prerequisites

```bash
which tmux    # must be installed
lsof -i :8000 # server must be running (the CLI needs a /ws endpoint)
```

If the server isn't running, start it first:

```bash
source .venv/bin/activate && readback &
sleep 3
```

## 1. Launch

Kill any stale test session, then start the CLI with `--no-spawn` (attach to
the running server, don't start a second one).

```bash
tmux kill-session -t rbtest 2>/dev/null
tmux new-session -d -s rbtest -x 100 -y 30 \
  "cd /Users/mks/Desktop/C0D3/readback/src/cli && bun run start -- --no-spawn 2>&1; echo '---EXITED---'; sleep 300"
sleep 2
```

Verify the input screen rendered:

```bash
tmux capture-pane -t rbtest -p | head -15
```

You should see the wordmark banner, the input box, and the status line.

## 2. Helpers

Use these throughout. All interaction is `send-keys` in, `capture-pane` out.

```bash
# Send a key / sequence
tmux send-keys -t rbtest '<KEY>' [Enter]

# Capture current screen
tmux capture-pane -t rbtest -p

# Check player state (icon line)
tmux capture-pane -t rbtest -p | grep -E '❚❚|▸ |↺ '

# Check for orphaned afplay
ps aux | grep afplay | grep -v grep

# Check screen type (look for distinguishing elements)
# input:   "Paste a URL"
# player:  "space pause/resume"
# library: "library —"
# busy:    phase name (loading/fetching/summarizing/synthesizing)
```

**Timing:** always `sleep` after `send-keys` before `capture-pane`. Use
0.3–0.5 s for key presses, 1–2 s for screen transitions, 2–3 s for server
round-trips (library fetch, audio resolve).

## 3. Test catalogue

Pick the tests that match your change. Not every run needs all of them.

### 3a. Playback — play from library

```bash
tmux send-keys -t rbtest '/lib' Enter
sleep 2
# Verify library screen
tmux capture-pane -t rbtest -p | grep 'library —'
# Play the first item (already selected)
tmux send-keys -t rbtest Enter
sleep 2
# Verify player screen, audio playing
tmux capture-pane -t rbtest -p | grep -E '❚❚|▸ |↺ '
```

### 3b. Pause / resume

```bash
# Pause
tmux send-keys -t rbtest ' '
sleep 0.5
tmux capture-pane -t rbtest -p | grep '▸ '   # paused icon

# Resume
tmux send-keys -t rbtest ' '
sleep 1
tmux capture-pane -t rbtest -p | grep '❚❚'   # playing icon
```

### 3c. Rapid toggle (race condition test)

```bash
# 4 rapid presses — should end on "playing" (even count)
tmux send-keys -t rbtest ' ' && sleep 0.1 && \
tmux send-keys -t rbtest ' ' && sleep 0.1 && \
tmux send-keys -t rbtest ' ' && sleep 0.1 && \
tmux send-keys -t rbtest ' '
sleep 1.5
tmux capture-pane -t rbtest -p | grep '❚❚'   # playing

# 3 rapid presses — should end on "paused" (odd count)
tmux send-keys -t rbtest ' ' && sleep 0.1 && \
tmux send-keys -t rbtest ' ' && sleep 0.1 && \
tmux send-keys -t rbtest ' '
sleep 1
tmux capture-pane -t rbtest -p | grep '▸ '   # paused

# No orphaned afplay after rapid toggling
ps aux | grep afplay | grep -v grep
```

### 3d. Seek

```bash
# Seek forward 5s
tmux send-keys -t rbtest Right
sleep 0.5
tmux capture-pane -t rbtest -p | grep -E '❚❚|▸ '

# Seek backward 5s
tmux send-keys -t rbtest Left
sleep 0.5
tmux capture-pane -t rbtest -p | grep -E '❚❚|▸ '

# Seek while paused (should resume at new position)
tmux send-keys -t rbtest ' '   # pause first
sleep 0.3
tmux send-keys -t rbtest Right
sleep 1
tmux capture-pane -t rbtest -p | grep '❚❚'   # resumed
```

### 3e. Back from player

```bash
tmux send-keys -t rbtest 'q'
sleep 0.5
# Verify input screen
tmux capture-pane -t rbtest -p | grep 'Paste a URL'
# No orphaned afplay
ps aux | grep afplay | grep -v grep
```

### 3f. Transcript toggle (summary mode only)

```bash
# From player screen with a summary-mode read:
tmux send-keys -t rbtest 't'
sleep 0.3
tmux capture-pane -t rbtest -p | grep 'hide transcript'

tmux send-keys -t rbtest 't'
sleep 0.3
tmux capture-pane -t rbtest -p | grep 'show transcript'
```

### 3g. Full read cycle (URL → play → back)

Only run this when testing the full pipeline, not just player controls. Takes
30 s–3 min depending on article length and mode.

```bash
# Type a short URL
tmux send-keys -t rbtest 'https://example.com' Enter
# Wait for synthesis (watch for player screen)
# Poll every 5s:
for i in $(seq 1 30); do
  sleep 5
  tmux capture-pane -t rbtest -p | grep -q 'space pause/resume' && break
done
tmux capture-pane -t rbtest -p | head -20
```

## 4. Teardown

Always clean up — a stale tmux session or orphaned afplay will confuse the
next run.

```bash
tmux send-keys -t rbtest '/quit' Enter
sleep 1
tmux kill-session -t rbtest 2>/dev/null
# Final orphan check
ps aux | grep afplay | grep -v grep
```

## 5. Interpreting results

| What you see | Meaning |
|---|---|
| Correct icon (`❚❚` / `▸` / `↺`) after toggle | Pause/resume state is in sync |
| Progress bar advances after resume | Timer restarted correctly |
| No afplay after `q` / quit | SIGKILL cleanup works |
| `---EXITED---` in capture | CLI crashed — check stderr |
| Stale icon / frozen bar after rapid toggle | State race — check `togglePause` generation logic |
| Two afplay in `ps` | Kill not instant — check `killProc` |

## 6. What this skill does NOT cover

- **Audio quality** (buffer artifacts, pops, silence gaps) — requires human ears.
- **Server pipeline** (extract, summarize, synthesize) — use the debug skill.
- **Dashboard** — separate surface, no tmux needed (`curl` the REST API).
- **Resize behavior** — tmux `resize-pane` can test this but it's fragile with Ink.
