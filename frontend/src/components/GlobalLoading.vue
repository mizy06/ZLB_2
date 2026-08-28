<!-- apps/kimi-web/src/components/GlobalLoading.vue -->
<!-- Full-screen splash shown on first load until the client has talked to the
     daemon, so a page refresh doesn't flash a half-rendered, not-yet-connected
     app. Hidden once the client initialization finishes. -->
<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import Spinner from './ui/Spinner.vue';
import BrandMark from './BrandMark.vue';
/** Last connection error from the first-load auth gate's retry loop, shown so
 *  a "cannot connect" state is diagnosable instead of a bare spinner. */
defineProps<{ issue?: string | null }>();
const { t } = useI18n();
</script>

<template>
  <div class="gload" role="status" :aria-label="t('app.connecting')">
    <div class="gload-box">
      <BrandMark class="gload-mark" :label="t('sidebar.brand')" />
      <div class="gload-logo">{{ t('sidebar.brand') }}</div>
      <Spinner size="md" :label="t('app.connecting')" />
      <div class="gload-text">{{ t('app.connecting') }}</div>
      <div v-if="issue" class="gload-issue">
        <div>{{ t('app.connectRetrying') }}</div>
        <div class="gload-issue-detail">{{ issue }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gload {
  position: fixed;
  top: 0;
  left: 0;
  /* Viewport units for size + position so the splash always fills the screen,
     even if a transformed/collapsed <html> would otherwise shrink a fixed box. */
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  min-width: 100vw;
  min-height: 100dvh;
  z-index: var(--z-toast);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}
.gload-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 22px;
  /* nudge slightly above center — feels more intentional than dead-center */
  transform: translateY(-6%);
}
.gload-logo {
  min-width: 128px;
  color: var(--color-text);
  font: var(--text-2xl) var(--font-ui);
  font-weight: var(--weight-medium);
  text-align: center;
  animation: gload-pop 0.55s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.gload-mark {
  width: 54px;
  height: 54px;
  animation: gload-pop 0.55s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.gload-text {
  font-family: var(--mono);
  font-size: var(--text-base);
  color: var(--muted);
  letter-spacing: 0.04em;
}
.gload-issue {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  max-width: min(480px, 80vw);
  font-family: var(--sans);
  font-size: var(--text-sm);
  color: var(--muted);
  text-align: center;
}
.gload-issue-detail {
  font-family: var(--mono);
  font-size: var(--text-xs);
  color: var(--muted);
  opacity: 0.8;
  word-break: break-word;
}
@keyframes gload-pop {
  from { opacity: 0; transform: translateY(6px) scale(0.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .gload-logo,
  .gload-mark { animation: none; }
}

.gload-text { font-family: var(--sans); }
</style>
