<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import { listReads, deleteRead, audioUrl, type Read, type Sort } from "./api";
import SearchBar from "./components/SearchBar.vue";
import SortToggle from "./components/SortToggle.vue";
import ReadCard from "./components/ReadCard.vue";

const PAGE_SIZE = 20;

const q = ref("");
const sort = ref<Sort>("newest");
const reads = ref<Read[]>([]);
const total = ref(0);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref<string | null>(null);

// One shared <audio> so only one read plays at a time. The card whose id is
// `activeId` shows the expanded player (controls + synced transcript).
const audio = new Audio();
const activeId = ref<string | null>(null);
const paused = ref(true);
const finished = ref(false);
const elapsed = ref(0);
const duration = ref(0);

audio.addEventListener("timeupdate", () => {
  elapsed.value = audio.currentTime;
});
audio.addEventListener("durationchange", () => {
  if (isFinite(audio.duration)) duration.value = audio.duration;
});
audio.addEventListener("play", () => {
  paused.value = false;
  finished.value = false;
});
audio.addEventListener("pause", () => {
  paused.value = true;
});
audio.addEventListener("ended", () => {
  finished.value = true;
  paused.value = true;
  elapsed.value = duration.value;
});

// Fresh load (mount / search / sort) — replaces the list with page 1.
async function load() {
  loading.value = true;
  error.value = null;
  try {
    const page = await listReads(q.value.trim(), sort.value, PAGE_SIZE, 0);
    reads.value = page.items;
    total.value = page.total;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

// Append the next page (offset = how many we already have).
async function loadMore() {
  if (loadingMore.value) return;
  loadingMore.value = true;
  try {
    const page = await listReads(q.value.trim(), sort.value, PAGE_SIZE, reads.value.length);
    reads.value = [...reads.value, ...page.items];
    total.value = page.total;
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loadingMore.value = false;
  }
}

// Debounce search; refetch immediately on sort change.
let timer: ReturnType<typeof setTimeout>;
watch(q, () => {
  clearTimeout(timer);
  timer = setTimeout(load, 220);
});
watch(sort, load);

function play(read: Read) {
  if (activeId.value === read.id) {
    // Same card: replay if finished, else toggle pause/resume.
    if (finished.value) {
      audio.currentTime = 0;
      audio.play();
    } else if (audio.paused) {
      audio.play();
    } else {
      audio.pause();
    }
    return;
  }
  // Switch to a different read.
  audio.src = audioUrl(read.audio_filename);
  elapsed.value = 0;
  duration.value = read.duration_sec; // until real metadata loads
  finished.value = false;
  activeId.value = read.id;
  audio.play();
}

function seek(fraction: number) {
  const total = isFinite(audio.duration) && audio.duration > 0 ? audio.duration : duration.value;
  if (total > 0) audio.currentTime = Math.max(0, Math.min(1, fraction)) * total;
  if (finished.value && fraction < 1) audio.play(); // scrubbing back un-finishes
}

function skip(deltaSec: number) {
  const total = isFinite(audio.duration) && audio.duration > 0 ? audio.duration : duration.value;
  audio.currentTime = Math.max(0, Math.min(total, audio.currentTime + deltaSec));
  if (finished.value && deltaSec < 0) audio.play();
}

async function onDelete(read: Read) {
  if (activeId.value === read.id) {
    audio.pause();
    activeId.value = null;
  }
  try {
    await deleteRead(read.id);
    reads.value = reads.value.filter((r) => r.id !== read.id);
    total.value = Math.max(0, total.value - 1);
  } catch (e) {
    error.value = (e as Error).message;
  }
}

// Keyboard parity with the CLI player: space = pause/resume (replay if finished),
// ←/→ = seek ±5 s. Ignored while typing in the search box.
function onKey(e: KeyboardEvent) {
  if (!activeId.value) return;
  const t = e.target as HTMLElement | null;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
  if (e.key === " ") {
    e.preventDefault();
    if (finished.value) {
      audio.currentTime = 0;
      audio.play();
    } else if (audio.paused) audio.play();
    else audio.pause();
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    skip(-5);
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    skip(5);
  }
}

onMounted(() => {
  load();
  window.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  clearTimeout(timer);
  window.removeEventListener("keydown", onKey);
  audio.pause();
});
</script>

<template>
  <main class="wrap">
    <header class="head">
      <p class="prompt-line"><span>~ $</span> readback-cli --library<span class="caret"></span></p>
      <div class="wordmark">read<span class="accent">back</span></div>
      <p class="subtitle">your library — replay any read, anytime</p>
    </header>

    <div class="controls">
      <SearchBar v-model="q" />
      <SortToggle v-model="sort" />
    </div>

    <p v-if="loading" class="muted loading">loading…</p>
    <p v-else-if="error" class="muted err">{{ error }}</p>
    <p v-else-if="reads.length === 0 && q" class="muted">no reads match “{{ q }}”.</p>
    <p v-else-if="reads.length === 0" class="muted">
      no reads yet — synthesize one with the CLI and it'll show up here.
    </p>

    <template v-else>
      <p class="count">
        {{ reads.length === total ? `${total} read${total === 1 ? "" : "s"}` : `showing ${reads.length} of ${total}` }}
      </p>
      <TransitionGroup tag="div" name="card" class="cards" appear>
        <ReadCard
          v-for="(read, i) in reads"
          :key="read.id"
          :style="{ '--i': Math.min(i, 8) }"
          :read="read"
          :active="activeId === read.id"
          :paused="paused"
          :finished="finished"
          :elapsed="activeId === read.id ? elapsed : 0"
          :duration="activeId === read.id ? duration : read.duration_sec"
          @play="play"
          @seek="seek"
          @skip="skip"
          @delete="onDelete"
        />
      </TransitionGroup>
      <button v-if="reads.length < total" class="load-more" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? "loading…" : `Load more (${total - reads.length})` }}
      </button>
    </template>

    <footer class="foot">readback · offline article reader · all on-device</footer>
  </main>
</template>
