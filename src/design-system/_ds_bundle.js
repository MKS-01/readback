(() => {
  var __create = Object.create;
  var __getProtoOf = Object.getPrototypeOf;
  var __defProp = Object.defineProperty;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  function __accessProp(key) {
    return this[key];
  }
  var __toESMCache_node;
  var __toESMCache_esm;
  var __toESM = (mod, isNodeMode, target) => {
    var canCache = mod != null && typeof mod === "object";
    if (canCache) {
      var cache = isNodeMode ? __toESMCache_node ??= new WeakMap : __toESMCache_esm ??= new WeakMap;
      var cached = cache.get(mod);
      if (cached)
        return cached;
    }
    target = mod != null ? __create(__getProtoOf(mod)) : {};
    const to = isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target;
    for (let key of __getOwnPropNames(mod))
      if (!__hasOwnProp.call(to, key))
        __defProp(to, key, {
          get: __accessProp.bind(mod, key),
          enumerable: true
        });
    if (canCache)
      cache.set(mod, to);
    return to;
  };
  var __require = function(x) {
    if (x === "react") return window.React;
    throw Error('Dynamic require of "' + x + '" is not supported');
  };

  // _ds_entry.jsx
  var import_react10 = __toESM(__require("react"));

  // components/feedback/Badge.jsx
  var import_react = __toESM(__require("react"));
  var TONE_COLOR = {
    accent: "var(--accent)",
    green: "var(--green)",
    yellow: "var(--yellow)",
    red: "var(--red)",
    dim: "var(--dim)"
  };
  var TONE_FILL = {
    accent: "var(--accent-08)",
    green: "var(--green-10)",
    yellow: "var(--yellow-10)",
    red: "var(--red-10)",
    dim: "transparent"
  };
  function Badge({
    children,
    color = "accent",
    variant = "chip",
    style = {}
  }) {
    if (variant === "text") {
      return /* @__PURE__ */ import_react.default.createElement("span", {
        style: {
          color: TONE_COLOR[color],
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-sm)",
          ...style
        }
      }, children);
    }
    return /* @__PURE__ */ import_react.default.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 9px",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-xs)",
        lineHeight: "var(--leading-normal)",
        color: TONE_COLOR[color],
        background: TONE_FILL[color],
        border: `1px solid ${color === "dim" ? "var(--line)" : TONE_COLOR[color]}`,
        borderRadius: "var(--radius-sm)",
        ...style
      }
    }, children);
  }

  // components/core/Button.jsx
  var import_react2 = __toESM(__require("react"));
  function Button({
    children,
    variant = "ghost",
    size = "md",
    href,
    disabled = false,
    onClick,
    style = {},
    ...rest
  }) {
    const [hover, setHover] = import_react2.useState(false);
    const [press, setPress] = import_react2.useState(false);
    const pad = size === "sm" ? "7px 14px" : "10px 22px";
    const fontSize = size === "sm" ? "var(--text-base)" : "var(--text-body)";
    const base = {
      display: "inline-flex",
      alignItems: "center",
      gap: 8,
      padding: pad,
      fontFamily: "var(--font-mono)",
      fontSize,
      lineHeight: 1.2,
      border: "1px solid var(--line)",
      borderRadius: "var(--radius)",
      color: "var(--text)",
      background: "none",
      cursor: disabled ? "default" : "pointer",
      opacity: disabled ? 0.5 : 1,
      textDecoration: "none",
      transition: "border-color var(--dur-fast), color var(--dur-fast), background var(--dur-fast), transform var(--dur-press) var(--ease-out)",
      transform: press ? "scale(0.97)" : hover && !disabled ? "translateY(-1px)" : "none"
    };
    const variants = {
      ghost: {
        borderColor: hover && !disabled ? "var(--dim)" : "var(--line)"
      },
      accent: {
        borderColor: hover && !disabled ? "var(--accent-hi)" : "var(--accent)",
        color: hover && !disabled ? "var(--accent-hi)" : "var(--accent)",
        background: hover && !disabled ? "var(--accent-14)" : "var(--accent-08)",
        transform: press ? "scale(0.97)" : "none"
      }
    };
    const styles = { ...base, ...variants[variant], ...style };
    const handlers = {
      onMouseEnter: () => setHover(true),
      onMouseLeave: () => {
        setHover(false);
        setPress(false);
      },
      onMouseDown: () => !disabled && setPress(true),
      onMouseUp: () => setPress(false),
      onClick: disabled ? undefined : onClick
    };
    if (href && !disabled) {
      return /* @__PURE__ */ import_react2.default.createElement("a", {
        href,
        style: styles,
        ...handlers,
        ...rest
      }, children);
    }
    return /* @__PURE__ */ import_react2.default.createElement("button", {
      type: "button",
      disabled,
      style: styles,
      ...handlers,
      ...rest
    }, children);
  }

  // components/core/PromptLine.jsx
  var import_react3 = __toESM(__require("react"));
  function PromptLine({
    cwd = "~",
    command,
    caret = true,
    style = {}
  }) {
    return /* @__PURE__ */ import_react3.default.createElement("p", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-base)",
        color: "var(--dim)",
        display: "flex",
        alignItems: "center",
        flexWrap: "wrap",
        ...style
      }
    }, /* @__PURE__ */ import_react3.default.createElement("span", null, cwd, " $"), command ? /* @__PURE__ */ import_react3.default.createElement("span", null, " ", command) : null, caret ? /* @__PURE__ */ import_react3.default.createElement(Caret, null) : null);
  }
  function Caret({ style = {} }) {
    return /* @__PURE__ */ import_react3.default.createElement("span", {
      "aria-hidden": "true",
      style: {
        display: "inline-block",
        width: 9,
        height: 3,
        marginLeft: 7,
        background: "var(--accent)",
        animation: "rb-blink 1.1s steps(1) infinite",
        ...style
      }
    });
  }

  // components/forms/SearchInput.jsx
  var import_react4 = __toESM(__require("react"));
  function SearchInput({
    value,
    onChange,
    placeholder = "search title, summary, url…",
    sigil = "/",
    style = {}
  }) {
    const [focus, setFocus] = import_react4.useState(false);
    return /* @__PURE__ */ import_react4.default.createElement("div", {
      style: {
        flex: 1,
        minWidth: 200,
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "9px 14px",
        background: "var(--panel)",
        border: `1px solid ${focus ? "var(--accent)" : "var(--line)"}`,
        borderRadius: "var(--radius)",
        transition: "border-color var(--dur-fast)",
        ...style
      }
    }, /* @__PURE__ */ import_react4.default.createElement("span", {
      style: { color: "var(--accent)", fontSize: "var(--text-base)", fontFamily: "var(--font-mono)" }
    }, sigil), /* @__PURE__ */ import_react4.default.createElement("input", {
      value,
      onChange: (e) => onChange && onChange(e.target.value),
      onFocus: () => setFocus(true),
      onBlur: () => setFocus(false),
      placeholder,
      style: {
        flex: 1,
        background: "none",
        border: "none",
        outline: "none",
        color: "var(--text)",
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-body)"
      }
    }));
  }

  // components/player/SeekBar.jsx
  var import_react5 = __toESM(__require("react"));
  function fmt(sec) {
    const s = Math.max(0, Math.floor(sec || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  function Skip({ children, onClick, label }) {
    return /* @__PURE__ */ import_react5.default.createElement("button", {
      onClick,
      "aria-label": label,
      style: {
        background: "none",
        border: "1px solid var(--line)",
        borderRadius: 6,
        color: "var(--dim)",
        fontSize: "var(--text-xs)",
        padding: "3px 8px",
        cursor: "pointer",
        fontFamily: "var(--font-mono)",
        transition: "border-color var(--dur-fast), color var(--dur-fast), transform var(--dur-press) var(--ease-out)"
      },
      onMouseEnter: (e) => {
        e.currentTarget.style.borderColor = "var(--accent)";
        e.currentTarget.style.color = "var(--accent)";
      },
      onMouseLeave: (e) => {
        e.currentTarget.style.borderColor = "var(--line)";
        e.currentTarget.style.color = "var(--dim)";
        e.currentTarget.style.transform = "none";
      },
      onMouseDown: (e) => e.currentTarget.style.transform = "scale(0.95)",
      onMouseUp: (e) => e.currentTarget.style.transform = "none"
    }, children);
  }
  function SeekBar({
    elapsed = 0,
    duration = 0,
    onSeek,
    onSkip,
    skips = true,
    style = {}
  }) {
    const frac = duration > 0 ? Math.min(elapsed / duration, 1) : 0;
    const seek = (e) => {
      if (!onSeek)
        return;
      const r = e.currentTarget.getBoundingClientRect();
      onSeek((e.clientX - r.left) / r.width);
    };
    return /* @__PURE__ */ import_react5.default.createElement("div", {
      style: { display: "flex", alignItems: "center", gap: 12, ...style }
    }, /* @__PURE__ */ import_react5.default.createElement("span", {
      style: { fontSize: "var(--text-sm)", color: "var(--text)", minWidth: 34, flexShrink: 0, fontFamily: "var(--font-mono)" }
    }, fmt(elapsed)), /* @__PURE__ */ import_react5.default.createElement("div", {
      onClick: seek,
      role: "slider",
      "aria-label": "Seek",
      style: { flex: 1, height: 14, display: "flex", alignItems: "center", cursor: "pointer", position: "relative" }
    }, /* @__PURE__ */ import_react5.default.createElement("span", {
      style: { position: "absolute", width: "100%", height: 3, background: "var(--line)" }
    }), /* @__PURE__ */ import_react5.default.createElement("span", {
      style: { position: "relative", height: 3, background: "var(--accent)", width: `${frac * 100}%`, minWidth: 1 }
    }, /* @__PURE__ */ import_react5.default.createElement("span", {
      style: { position: "absolute", right: -4, top: "50%", width: 8, height: 8, transform: "translateY(-50%)", background: "var(--accent)", borderRadius: "50%" }
    }))), /* @__PURE__ */ import_react5.default.createElement("span", {
      style: { fontSize: "var(--text-sm)", color: "var(--dim)", minWidth: 34, textAlign: "right", flexShrink: 0, fontFamily: "var(--font-mono)" }
    }, fmt(duration)), skips && /* @__PURE__ */ import_react5.default.createElement("div", {
      style: { display: "flex", gap: 6, flexShrink: 0 }
    }, /* @__PURE__ */ import_react5.default.createElement(Skip, {
      label: "Back 5 seconds",
      onClick: () => onSkip && onSkip(-5)
    }, "« 5s"), /* @__PURE__ */ import_react5.default.createElement(Skip, {
      label: "Forward 5 seconds",
      onClick: () => onSkip && onSkip(5)
    }, "5s »")));
  }

  // components/player/WaveformPlayer.jsx
  var import_react6 = __toESM(__require("react"));
  function fmt2(s) {
    return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  }
  function WaveformPlayer({ bars = 52, duration = 111, style = {} }) {
    const [playing, setPlaying] = import_react6.useState(false);
    const [t, setT] = import_react6.useState(0);
    const raf = import_react6.useRef(null);
    const last = import_react6.useRef(null);
    import_react6.useEffect(() => {
      if (!playing)
        return;
      const tick = (now) => {
        if (last.current == null)
          last.current = now;
        const dt = (now - last.current) / 1000;
        last.current = now;
        setT((prev) => {
          const next = prev + dt;
          if (next >= duration) {
            setPlaying(false);
            return duration;
          }
          return next;
        });
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);
      return () => {
        cancelAnimationFrame(raf.current);
        last.current = null;
      };
    }, [playing, duration]);
    const frac = duration ? t / duration : 0;
    const lit = Math.floor(frac * bars);
    const heights = Array.from({ length: bars }, (_, i) => {
      const h = 22 + 70 * Math.abs(Math.sin(i * 7.31) * 0.6 + Math.sin(i * 1.7) * 0.4);
      return Math.min(h, 95);
    });
    const seek = (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      setT(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * duration);
    };
    return /* @__PURE__ */ import_react6.default.createElement("div", {
      style: { display: "flex", alignItems: "center", gap: 18, padding: "6px 0", ...style }
    }, /* @__PURE__ */ import_react6.default.createElement("button", {
      onClick: () => {
        if (t >= duration)
          setT(0);
        setPlaying((p) => !p);
      },
      "aria-label": playing ? "Pause" : "Play",
      style: {
        width: "var(--control-h)",
        height: "var(--control-h)",
        flexShrink: 0,
        background: "none",
        border: "1px solid var(--accent)",
        color: "var(--accent)",
        borderRadius: "var(--radius)",
        fontSize: "var(--text-base)",
        cursor: "pointer",
        transition: "background var(--dur-fast), transform var(--dur-press) var(--ease-out)"
      },
      onMouseDown: (e) => e.currentTarget.style.transform = "scale(0.95)",
      onMouseUp: (e) => e.currentTarget.style.transform = "none",
      onMouseLeave: (e) => e.currentTarget.style.transform = "none"
    }, playing ? "❚❚" : "▶"), /* @__PURE__ */ import_react6.default.createElement("div", {
      onClick: seek,
      style: { flex: 1, display: "flex", alignItems: "center", gap: 3, height: 38, cursor: "pointer" }
    }, heights.map((h, i) => {
      const on = i < lit;
      return /* @__PURE__ */ import_react6.default.createElement("i", {
        key: i,
        style: {
          flex: 1,
          height: `${h}%`,
          background: on ? "var(--accent)" : "var(--line)",
          transition: "background var(--dur-base) var(--ease-out)",
          transformOrigin: "center",
          animation: playing && on ? "rb-sway 0.9s ease-in-out infinite alternate" : "none",
          animationDelay: `${i % 7 * 0.11}s`
        }
      });
    })), /* @__PURE__ */ import_react6.default.createElement("span", {
      style: { color: "var(--dim)", fontSize: "var(--text-base)", minWidth: 86, textAlign: "right", flexShrink: 0, fontFamily: "var(--font-mono)" }
    }, fmt2(t), " / ", fmt2(duration)), /* @__PURE__ */ import_react6.default.createElement("style", null, `@keyframes rb-sway { to { transform: scaleY(0.45); } }`));
  }

  // components/content/ReadCard.jsx
  var import_react7 = __toESM(__require("react"));
  function fmt3(sec) {
    const s = Math.max(0, Math.floor(sec || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  function ReadCard({
    title,
    date,
    duration = 111,
    mode = "summary",
    voice = "codeword",
    words = 0,
    snippet = "",
    sourceUrl = "#",
    style = {}
  }) {
    const [active, setActive] = import_react7.useState(false);
    const [playing, setPlaying] = import_react7.useState(false);
    const [t, setT] = import_react7.useState(0);
    const raf = import_react7.useRef(null);
    const last = import_react7.useRef(null);
    import_react7.useEffect(() => {
      if (!playing)
        return;
      const tick = (now) => {
        if (last.current == null)
          last.current = now;
        const dt = (now - last.current) / 1000;
        last.current = now;
        setT((p) => {
          const n = p + dt;
          if (n >= duration) {
            setPlaying(false);
            return duration;
          }
          return n;
        });
        raf.current = requestAnimationFrame(tick);
      };
      raf.current = requestAnimationFrame(tick);
      return () => {
        cancelAnimationFrame(raf.current);
        last.current = null;
      };
    }, [playing, duration]);
    const onPlay = () => {
      if (!active) {
        setActive(true);
        setPlaying(true);
        return;
      }
      if (t >= duration) {
        setT(0);
        setPlaying(true);
        return;
      }
      setPlaying((p) => !p);
    };
    const isSummary = mode === "summary";
    const playIcon = active && t >= duration ? "↺" : active && playing ? "❚❚" : "▶";
    const wordsArr = snippet.split(/\s+/).filter(Boolean);
    const lens = wordsArr.map((w) => w.length);
    const totalW = lens.reduce((a, b) => a + b, 0);
    const target = duration > 0 ? t / duration * totalW : 0;
    let spoken = 0, acc = 0;
    for (const l of lens) {
      acc += l;
      if (acc <= target)
        spoken++;
      else
        break;
    }
    const spokenText = wordsArr.slice(0, spoken).join(" ");
    const restText = wordsArr.slice(spoken).join(" ");
    return /* @__PURE__ */ import_react7.default.createElement("article", {
      style: {
        background: active ? "var(--panel)" : "var(--bg)",
        boxShadow: active ? "var(--rail-accent)" : "none",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius)",
        padding: "20px 22px",
        fontFamily: "var(--font-mono)",
        transition: "background var(--dur-base) var(--ease-out)",
        ...style
      }
    }, /* @__PURE__ */ import_react7.default.createElement("div", {
      style: { display: "flex", alignItems: "flex-start", gap: 16 }
    }, /* @__PURE__ */ import_react7.default.createElement("button", {
      onClick: onPlay,
      "aria-label": playing ? "Pause" : "Play",
      style: {
        width: "var(--control-h)",
        height: "var(--control-h)",
        flexShrink: 0,
        background: active && playing ? "var(--accent)" : "none",
        color: active && playing ? "var(--bg)" : "var(--accent)",
        border: "1px solid var(--accent)",
        borderRadius: "var(--radius)",
        fontSize: "var(--text-body)",
        cursor: "pointer",
        transition: "background var(--dur-fast), transform var(--dur-press) var(--ease-out)"
      },
      onMouseDown: (e) => e.currentTarget.style.transform = "scale(0.95)",
      onMouseUp: (e) => e.currentTarget.style.transform = "none",
      onMouseLeave: (e) => e.currentTarget.style.transform = "none"
    }, playIcon), /* @__PURE__ */ import_react7.default.createElement("div", {
      style: { flex: 1, minWidth: 0 }
    }, /* @__PURE__ */ import_react7.default.createElement("h3", {
      style: { fontSize: "var(--text-body)", fontWeight: 600, lineHeight: 1.4, color: "var(--text)", overflowWrap: "anywhere" }
    }, title), /* @__PURE__ */ import_react7.default.createElement("div", {
      style: { color: "var(--dim)", fontSize: "var(--text-sm)", marginTop: 5, display: "flex", flexWrap: "wrap", gap: "4px 10px" }
    }, /* @__PURE__ */ import_react7.default.createElement("span", null, date), /* @__PURE__ */ import_react7.default.createElement("span", null, "· ", fmt3(duration)), /* @__PURE__ */ import_react7.default.createElement("span", null, "· ", /* @__PURE__ */ import_react7.default.createElement(Badge, {
      variant: "text",
      color: isSummary ? "accent" : "dim"
    }, mode)), /* @__PURE__ */ import_react7.default.createElement("span", null, "· ", voice), words ? /* @__PURE__ */ import_react7.default.createElement("span", null, "· ", words, " words") : null), active && isSummary ? /* @__PURE__ */ import_react7.default.createElement("p", {
      style: { fontSize: "var(--text-base)", marginTop: 10, lineHeight: 1.75, color: "var(--dim)", overflowWrap: "anywhere" }
    }, /* @__PURE__ */ import_react7.default.createElement("span", {
      style: { color: "var(--accent)" }
    }, spokenText), spokenText && restText ? " " : "", restText) : snippet ? /* @__PURE__ */ import_react7.default.createElement("p", {
      style: {
        color: "var(--dim)",
        fontSize: "var(--text-base)",
        marginTop: 10,
        whiteSpace: "pre-wrap",
        overflowWrap: "anywhere",
        display: "-webkit-box",
        WebkitLineClamp: 3,
        WebkitBoxOrient: "vertical",
        overflow: "hidden"
      }
    }, snippet) : null, active && /* @__PURE__ */ import_react7.default.createElement("div", {
      style: { paddingTop: 14 }
    }, /* @__PURE__ */ import_react7.default.createElement(SeekBar, {
      elapsed: t,
      duration,
      onSeek: (f) => setT(Math.max(0, Math.min(1, f)) * duration),
      onSkip: (d) => setT((p) => Math.max(0, Math.min(duration, p + d)))
    })), /* @__PURE__ */ import_react7.default.createElement("div", {
      style: { display: "flex", gap: 16, marginTop: 12, fontSize: "var(--text-sm)" }
    }, /* @__PURE__ */ import_react7.default.createElement("a", {
      href: sourceUrl,
      target: "_blank",
      rel: "noopener",
      style: { color: "var(--accent)" }
    }, "read original ↗"), /* @__PURE__ */ import_react7.default.createElement("button", {
      style: { background: "none", border: "none", color: "var(--dim)", padding: 0, cursor: "pointer", fontFamily: "inherit", fontSize: "var(--text-sm)" }
    }, "delete")))));
  }

  // components/brand/Wordmark.jsx
  var import_react8 = __toESM(__require("react"));
  function Wordmark({
    variant = "image",
    height = 32,
    src,
    subtitle,
    style = {}
  }) {
    if (variant === "ascii") {
      return /* @__PURE__ */ import_react8.default.createElement("div", {
        style: { fontFamily: "var(--font-mono)", lineHeight: 1, ...style }
      }, /* @__PURE__ */ import_react8.default.createElement("pre", {
        style: { fontSize: height * 0.28, color: "var(--text)", margin: 0, letterSpacing: "0.05em" }
      }, `▐█▀▀  █▀▀  █▀█  █▀▄  █▀▄  █▀█  █▀▀  █▄▀
`, "▐█▀▄  ██▄  █▀█  █▄▀  █▀▄  █▀█  █▄▄  █ █"), subtitle && /* @__PURE__ */ import_react8.default.createElement("p", {
        style: { fontFamily: "var(--font-display)", fontWeight: 500, fontSize: "var(--text-base)", color: "var(--dim)", marginTop: 6 }
      }, subtitle));
    }
    return /* @__PURE__ */ import_react8.default.createElement("div", {
      style
    }, /* @__PURE__ */ import_react8.default.createElement("img", {
      src,
      alt: "readback",
      height,
      style: { display: "block", height, width: "auto", imageRendering: "pixelated" }
    }), subtitle && /* @__PURE__ */ import_react8.default.createElement("p", {
      style: { fontFamily: "var(--font-display)", fontWeight: 500, fontSize: "var(--text-base)", color: "var(--dim)", marginTop: 6 }
    }, subtitle));
  }

  // components/layout/SectionHeader.jsx
  var import_react9 = __toESM(__require("react"));
  function SectionHeader({ children, style = {} }) {
    return /* @__PURE__ */ import_react9.default.createElement("h2", {
      style: {
        fontFamily: "var(--font-display)",
        fontSize: "var(--text-lg)",
        fontWeight: 700,
        letterSpacing: "0.03em",
        paddingBottom: 14,
        marginBottom: 24,
        borderBottom: "1px solid var(--line)",
        color: "var(--text)",
        ...style
      }
    }, children);
  }

  // _ds_entry.jsx
  var NS = {
    Badge,
    Button,
    Caret,
    PromptLine,
    SearchInput,
    SeekBar,
    WaveformPlayer,
    ReadCard,
    Wordmark,
    SectionHeader
  };
  window.ReadbackDesignSystem_7af2ab = NS;
})();
