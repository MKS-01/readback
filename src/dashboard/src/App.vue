<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from "vue";
import { listReads, deleteRead, audioUrl, type Read, type Sort } from "./api";
import SearchBar from "./components/SearchBar.vue";
import SortToggle from "./components/SortToggle.vue";
import ReadCard from "./components/ReadCard.vue";

const q = ref("");
const sort = ref<Sort>("newest");
const reads = ref<Read[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);

// One shared <audio> so only one read plays at a time.
const audio = new Audio();
const playingId = ref<string | null>(null);
const progress = ref(0);

audio.addEventListener("timeupdate", () => {
  progress.value = audio.duration ? audio.currentTime / audio.duration : 0;
});
audio.addEventListener("ended", () => {
  playingId.value = null;
  progress.value = 0;
});

async function load() {
  loading.value = true;
  error.value = null;
  try {
    reads.value = await listReads(q.value.trim(), sort.value);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
}

// Debounce search; refetch immediately on sort change.
let timer: ReturnType<typeof setTimeout>;
watch(q, () => {
  clearTimeout(timer);
  timer = setTimeout(load, 220);
});
watch(sort, load);

function onPlay(read: Read) {
  if (playingId.value === read.id) {
    if (audio.paused) audio.play();
    else {
      audio.pause();
      playingId.value = null; // paused reads as "not playing"
    }
    return;
  }
  audio.src = audioUrl(read.audio_filename);
  audio.currentTime = 0;
  audio.play();
  playingId.value = read.id;
}

async function onDelete(read: Read) {
  if (playingId.value === read.id) {
    audio.pause();
    playingId.value = null;
  }
  try {
    await deleteRead(read.id);
    reads.value = reads.value.filter((r) => r.id !== read.id);
  } catch (e) {
    error.value = (e as Error).message;
  }
}

onMounted(load);
onBeforeUnmount(() => {
  clearTimeout(timer);
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

    <p v-if="loading" class="muted">loading…</p>
    <p v-else-if="error" class="muted err">{{ error }}</p>
    <p v-else-if="reads.length === 0 && q" class="muted">no reads match “{{ q }}”.</p>
    <p v-else-if="reads.length === 0" class="muted">
      no reads yet — synthesize one with the CLI and it'll show up here.
    </p>

    <template v-else>
      <p class="count">{{ reads.length }} read{{ reads.length === 1 ? "" : "s" }}</p>
      <div class="cards">
        <ReadCard
          v-for="read in reads"
          :key="read.id"
          :read="read"
          :playing="playingId === read.id"
          :progress="progress"
          @play="onPlay"
          @delete="onDelete"
        />
      </div>
    </template>

    <footer class="foot">readback · offline article reader · all on-device</footer>
  </main>
</template>
