<script setup lang="ts">
defineProps<{ modelValue: string }>();
const emit = defineEmits<{ "update:modelValue": [string] }>();
</script>

<template>
  <label class="search">
    <span class="sigil">/</span>
    <input
      type="search"
      placeholder="search title, summary, url…"
      :value="modelValue"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
  </label>
</template>
