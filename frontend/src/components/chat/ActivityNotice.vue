<script setup lang="ts">
import { computed } from 'vue';

const props = defineProps<{
  label: string;
}>();

const characters = computed(() => Array.from(props.label));
</script>

<template>
  <div class="activity-notice" role="status" aria-live="polite">
    <span class="sr-only">{{ label }}</span>
    <span class="compaction-wave" aria-hidden="true">
      <span
        v-for="(character, index) in characters"
        :key="`${character}-${index}`"
        class="compaction-character"
        :style="{ animationDelay: `${index * 75}ms` }"
      >{{ character }}</span>
    </span>
  </div>
</template>

<style scoped>
.activity-notice {
  display: flex;
  align-items: center;
  align-self: flex-start;
  margin: 0;
  font: var(--text-sm)/var(--leading-normal) var(--font-ui);
  color: var(--color-text-muted);
}

.compaction-wave {
  display: inline-flex;
}

.compaction-character {
  animation: compaction-pulse 1.1s ease-in-out infinite;
}

@keyframes compaction-pulse {
  0%,
  100% {
    opacity: 0.28;
  }

  42% {
    opacity: 0.9;
  }

  66% {
    opacity: 0.48;
  }
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (prefers-reduced-motion: reduce) {
  .compaction-character {
    animation: none;
    opacity: 0.72;
  }
}
</style>
