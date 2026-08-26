<!-- apps/kimi-web/src/components/ui/MoonSpinner.vue -->
<!-- Agent working / waiting spinner: 3D rotating TopoMind brand mark.
     Used for "message sent, waiting for Agent response". Pauses on reduced motion. -->
<script setup lang="ts">
withDefaults(
  defineProps<{
    size?: 'sm' | 'md' | 'lg';
    fast?: boolean;
    label?: string;
  }>(),
  {
    size: 'md',
    label: 'Waiting for response…',
  },
);
</script>

<template>
  <span
    class="ui-moon"
    :class="[`ui-moon--${size}`, { 'ui-moon--fast': fast }]"
    :aria-label="label"
    role="img"
  >
    <svg
      class="brand-3d-spinner"
      viewBox="0 0 256 256"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <g class="brand-branches" fill="none" stroke-linecap="round" stroke-linejoin="round">
        <path d="M128 222V48" stroke-width="20" />
        <path d="M128 108c-19 0-32-7-45-20L68 73" stroke-width="18" />
        <path d="M128 145c-24 0-40 4-58 18L54 176" stroke-width="18" />
        <path d="M128 119c20 0 34-4 49-14l18-13" stroke-width="18" />
        <path d="M128 158c24 0 40 5 57 18l15 12" stroke-width="18" />
      </g>
      <circle class="brand-node brand-node-primary" cx="128" cy="48" r="15" />
      <circle class="brand-node" cx="68" cy="73" r="15" />
      <circle class="brand-node" cx="54" cy="176" r="15" />
      <circle class="brand-node brand-node-signal" cx="195" cy="92" r="15" />
      <circle class="brand-node" cx="200" cy="188" r="15" />
    </svg>
  </span>
</template>

<style scoped>
.ui-moon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  line-height: 1;
  user-select: none;
  flex: none;
  perspective: 500px;
  vertical-align: middle;
}
.ui-moon--sm { width: 16px; height: 16px; }
.ui-moon--md { width: 20px; height: 20px; }
.ui-moon--lg { width: 26px; height: 26px; }

.brand-3d-spinner {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
  transform-style: preserve-3d;
  animation: brand-3d-rotate 1.8s linear infinite;
  filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.15));
}

.ui-moon--fast .brand-3d-spinner {
  animation-duration: 0.9s;
}

.brand-branches {
  stroke: var(--brand-graphite, currentColor);
}

.brand-node {
  fill: var(--brand-graphite, currentColor);
}

.brand-node-primary {
  fill: var(--brand-blue, #245beb);
}

.brand-node-signal {
  fill: var(--brand-coral, #ff654f);
}

@keyframes brand-3d-rotate {
  0% {
    transform: rotateY(0deg) rotateX(10deg);
  }
  50% {
    transform: rotateY(180deg) rotateX(-10deg);
  }
  100% {
    transform: rotateY(360deg) rotateX(10deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .brand-3d-spinner {
    animation: none;
    transform: rotateY(0deg) rotateX(0deg);
  }
}
</style>

