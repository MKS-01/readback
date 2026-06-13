<script setup lang="ts">
import type { Sort } from "../api";

defineProps<{ modelValue: Sort }>();
const emit = defineEmits<{ "update:modelValue": [Sort] }>();
</script>

<template>
  <div class="sort" role="group" aria-label="Sort order">
    <button :class="{ on: modelValue === 'newest' }" @click="emit('update:modelValue', 'newest')">
      Newest
    </button>
    <button :class="{ on: modelValue === 'oldest' }" @click="emit('update:modelValue', 'oldest')">
      Oldest
    </button>
  </div>
</template>
