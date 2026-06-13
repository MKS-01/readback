<script setup lang="ts">
import { ref, computed } from "vue";
import type { Read } from "../api";

const props = defineProps<{
  read: Read;
  playing: boolean;
  progress: number; // 0..1, only meaningful while playing
}>();

const emit = defineEmits<{ play: [Read]; delete: [Read] }>();

const expanded = ref(false);
const confirming = ref(false);

// Summary mode → the spoken summary; Full mode → the article excerpt preview.
const snippet = computed(() => props.read.summary ?? props.read.excerpt);
const canExpand = computed(() => (snippet.value?.length ?? 0) > 180);

const fmtDate = computed(() => {
  const d = new Date(props.read.created_at);
  return isNaN(d.getTime())
    ? props.read.created_at
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
});

const fmtDuration = computed(() => {
  const s = Math.round(props.read.duration_sec);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
});

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
  <article class="card">
    <div class="card-top">
      <button
        class="play"
        :class="{ on: playing }"
        :aria-label="playing ? 'Pause' : 'Play'"
        @click="emit('play', read)"
      >
        {{ playing ? "❚❚" : "▶" }}
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

        <p v-if="snippet" class="snippet" :class="{ clamp: !expanded }">{{ snippet }}</p>

        <div class="actions">
          <button v-if="canExpand" @click="expanded = !expanded">
            {{ expanded ? "Show less" : "Show more" }}
          </button>
          <a :href="read.source_url" target="_blank" rel="noopener">read original ↗</a>
          <button class="danger" :class="{ confirm: confirming }" @click="onDelete" @blur="confirming = false">
            {{ confirming ? "click to confirm" : "delete" }}
          </button>
        </div>

        <div v-if="playing" class="bar"><span :style="{ width: progress * 100 + '%' }" /></div>
      </div>
    </div>
  </article>
</template>
