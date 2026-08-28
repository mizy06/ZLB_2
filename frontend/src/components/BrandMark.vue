<script setup lang="ts">
withDefaults(
  defineProps<{
    label?: string;
  }>(),
  {
    label: 'TopoMind',
  },
);
</script>

<template>
  <svg
    class="brand-mark"
    viewBox="0 0 256 256"
    xmlns="http://www.w3.org/2000/svg"
    role="img"
    :aria-label="label"
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
</template>

<style scoped>
.brand-mark {
  display: block;
  overflow: visible;
}
.brand-branches {
  stroke: var(--brand-graphite);
}
.brand-node {
  fill: var(--brand-graphite);
}
.brand-node-primary {
  fill: var(--brand-blue);
}
.brand-node-signal {
  fill: var(--brand-coral);
}
</style>
