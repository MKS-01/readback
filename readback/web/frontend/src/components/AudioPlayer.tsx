// Custom audio player for the reader result. A hidden <audio> does the real
// playback; the UI (play/pause button, current time, seek track, duration) is
// driven off its media events so it matches the dark Ghost theme instead of the
// browser's default controls. Seeking writes back to audio.currentTime.

import { useEffect, useRef, useState } from "react";
import { PauseIcon, ResumeIcon } from "./icons";

function mmss(sec: number): string {
  if (!isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface Props {
  src: string;
  // Fallback duration (seconds) from the server, used until metadata loads.
  duration: number;
  onPlay?: () => void;
  onPause?: () => void;
  onEnded?: () => void;
}

export function AudioPlayer({ src, duration, onPlay, onPause, onEnded }: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [total, setTotal] = useState(duration);

  // Reset when the source changes (a new read job).
  useEffect(() => {
    setCurrent(0);
    setTotal(duration);
  }, [src, duration]);

  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) a.play().catch(() => {});
    else a.pause();
  };

  const seek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const a = audioRef.current;
    if (!a) return;
    const t = Number(e.target.value);
    a.currentTime = t;
    setCurrent(t);
  };

  const dur = total > 0 ? total : duration;
  const pct = dur > 0 ? (current / dur) * 100 : 0;

  return (
    <div className="reader-player">
      <audio
        ref={audioRef}
        src={src}
        autoPlay
        onLoadedMetadata={(e) => {
          const d = e.currentTarget.duration;
          if (isFinite(d) && d > 0) setTotal(d);
        }}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
        onPlay={() => {
          setPlaying(true);
          onPlay?.();
        }}
        onPause={() => {
          setPlaying(false);
          onPause?.();
        }}
        onEnded={() => {
          setPlaying(false);
          onEnded?.();
        }}
      />
      <button
        type="button"
        className="reader-player-btn"
        onClick={toggle}
        aria-label={playing ? "Pause" : "Play"}
      >
        {playing ? <PauseIcon size={16} /> : <ResumeIcon size={16} />}
      </button>
      <span className="reader-player-time">{mmss(current)}</span>
      <input
        className="reader-player-track"
        type="range"
        min={0}
        max={dur || 0}
        step={0.1}
        value={Math.min(current, dur || 0)}
        onChange={seek}
        style={{ ["--pct" as string]: `${pct}%` }}
        aria-label="Seek"
      />
      <span className="reader-player-time reader-player-dur">{mmss(dur)}</span>
    </div>
  );
}
