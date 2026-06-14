<script setup lang="ts">
import { ref, computed } from "vue";
import type { Read } from "../api";

const props = defineProps<{
  read: Read;
  active: boolean; // this card owns the shared player
  paused: boolean;
  finished: boolean;
  elapsed: number; // seconds (only meaningful while active)
  duration: number; // seconds
}>();

const emit = defineEmits<{
  play: [Read];
  seek: [number]; // fraction 0..1
  skip: [number]; // delta seconds
  delete: [Read];
}>();

const showMore = ref(false);
const confirming = ref(false);

// Summary mode → the spoken summary (also the karaoke transcript while playing);
// Full mode → the article excerpt preview.
const snippet = computed(() => props.read.summary ?? props.read.excerpt);
const isSummary = computed(() => props.read.mode === "summary" && !!props.read.summary);
const canExpand = computed(() => (snippet.value?.length ?? 0) > 180);

function fmt(sec: number): string {
  const s = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const fmtDate = computed(() => {
  const d = new Date(props.read.created_at);
  return isNaN(d.getTime())
    ? props.read.created_at
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
});

const total = computed(() => props.duration || props.read.duration_sec);
const fmtDuration = computed(() => fmt(total.value));
const progress = computed(() => (total.value > 0 ? Math.min(props.elapsed / total.value, 1) : 0));

const playIcon = computed(() =>
  props.active && props.finished ? "↺" : props.active && !props.paused ? "❚❚" : "▶"
);

// ── Karaoke transcript: each word gets a share of the duration proportional to
// its char count (no per-word timestamps exist), exactly like the CLI player. ──
const words = computed(() => snippet.value.split(/\s+/).filter(Boolean));
const spokenCount = computed(() => {
  const lens = words.value.map((w) => w.length);
  const totalWeight = lens.reduce((a, b) => a + b, 0);
  if (totalWeight === 0 || total.value <= 0) return 0;
  const target = (props.elapsed / total.value) * totalWeight;
  let acc = 0;
  let n = 0;
  for (const l of lens) {
    acc += l;
    if (acc <= target) n++;
    else break;
  }
  return n;
});
// Two segments (blue spoken / dim rest). The joining space lives in a dynamic
// value so Vue's whitespace-condensing doesn't strip it (a static "<span> </span>"
// would render empty → words glue together and overflow the card).
const spokenText = computed(() => words.value.slice(0, spokenCount.value).join(" "));
const restText = computed(() => words.value.slice(spokenCount.value).join(" "));
const joiner = computed(() => (spokenText.value && restText.value ? " " : ""));

function onBarClick(e: MouseEvent) {
  const el = e.currentTarget as HTMLElement;
  const rect = el.getBoundingClientRect();
  emit("seek", (e.clientX - rect.left) / rect.width);
}

function onDelete() {
  if (confirming.value) {
    emit("delete", props.read);
    confirming.value = false;
  } else {
    confirming.value = true;
  }
}
</script>

<template>
  <article class="card" :class="{ active }">
    <div class="card-top">
      <button
        class="play"
        :class="{ on: active && !paused && !finished }"
        :aria-label="active && !paused ? 'Pause' : 'Play'"
        @click="emit('play', read)"
      >
        {{ playIcon }}
      </button>

      <div class="card-body">
        <h3 class="title">{{ read.title }}</h3>

        <div class="meta">
          <span>{{ fmtDate }}</span>
          <span>· {{ fmtDuration }}</span>
          <span :class="{ 'mode-summary': read.mode === 'summary' }">· {{ read.mode }}</span>
          <span>· {{ read.voice }}</span>
          <span>· {{ read.word_count }} words</span>
        </div>

        <!-- Active + summary → karaoke transcript; otherwise the static snippet. -->
        <p v-if="active && isSummary" class="transcript"><span class="spoken">{{ spokenText }}</span>{{ joiner }}{{ restText }}</p>
        <p v-else-if="snippet" class="snippet" :class="{ clamp: !showMore }">{{ snippet }}</p>

        <!-- Player controls (only while this card is active). The grid-rows
             wrapper lets it accordion open/closed in pure CSS (see styles.css). -->
        <Transition name="player">
          <div v-if="active" class="player-panel">
            <div class="player">
              <span class="t">{{ fmt(elapsed) }}</span>
              <div class="track" @click="onBarClick" role="slider" aria-label="Seek">
                <div class="fill" :style="{ width: progress * 100 + '%' }">
                  <span class="knob"></span>
                </div>
              </div>
              <span class="t dim">{{ fmt(total) }}</span>
              <div class="skips">
                <button @click="emit('skip', -5)" aria-label="Back 5 seconds">« 5s</button>
                <button @click="emit('skip', 5)" aria-label="Forward 5 seconds">5s »</button>
              </div>
            </div>
          </div>
        </Transition>

        <div class="actions">
          <button v-if="!active && canExpand" @click="showMore = !showMore">
            {{ showMore ? "Show less" : "Show more" }}
          </button>
          <a :href="read.source_url" target="_blank" rel="noopener">read original ↗</a>
          <button class="danger" :class="{ confirm: confirming }" @click="onDelete" @blur="confirming = false">
            {{ confirming ? "click to confirm" : "delete" }}
          </button>
        </div>
      </div>
    </div>
  </article>
</template>
