<!-- apps/kimi-web/src/components/settings/Onboarding.vue -->
<!-- Optional preferences dialog: the main interface is shown directly on first
     load; this remains available only when explicitly reopened from Settings. -->
<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import { availableLocales, setLocale, type LocaleCode } from '../../i18n';
import { useAppearance, type Accent } from '../../composables/client/useAppearance';
import Button from '../ui/Button.vue';
import Dialog from '../ui/Dialog.vue';
import SegmentedControl from '../ui/SegmentedControl.vue';
import BrandMark from '../BrandMark.vue';

const emit = defineEmits<{ complete: []; skip: [] }>();

const { t, locale } = useI18n();
const { accent, setAccent } = useAppearance();

function chooseLocale(code: LocaleCode): void {
  if (locale.value !== code) setLocale(code);
}

function finish(): void {
  emit('complete');
}
</script>

<template>
  <Dialog
    :open="true"
    size="md"
    :close-on-overlay="false"
    :close-on-esc="false"
    @close="emit('skip')"
  >
    <template #head>
      <div class="ob-brand">
        <BrandMark class="ob-logo" :label="t('sidebar.brand')" />
        <div class="ob-brand-text">
          <div class="ob-title">{{ t('onboarding.title') }}</div>
          <div class="ob-sub">{{ t('onboarding.subtitle') }}</div>
        </div>
      </div>
    </template>

    <section class="ob-sec">
      <div class="ob-label">{{ t('onboarding.languageLabel') }}</div>
      <SegmentedControl
        :model-value="locale"
        :options="availableLocales.map((l) => ({ value: l.code, label: l.label }))"
        @update:model-value="chooseLocale($event as LocaleCode)"
      />
    </section>

    <section class="ob-sec">
      <div class="ob-label">{{ t('theme.accentLabel') }}</div>
      <SegmentedControl
        :model-value="accent"
        :options="[
          { value: 'blue', label: t('theme.accentBlue') },
          { value: 'mono', label: t('theme.accentBlack') },
        ]"
        @update:model-value="setAccent($event as Accent)"
      />
    </section>

    <Button variant="primary" size="lg" class="ob-start" @click="finish">{{ t('onboarding.start') }}</Button>
  </Dialog>
</template>

<style scoped>
.ob-brand {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.ob-brand-text { min-width: 0; }
.ob-logo {
  width: 44px; height: 44px; flex: none;
}
.ob-title { color: var(--color-text); font-size: var(--text-xl); font-weight: var(--weight-medium); }
.ob-sub { color: var(--color-text-muted); font-size: var(--text-base); margin-top: 1px; }

.ob-sec { margin-bottom: var(--space-4); }
.ob-label { color: var(--color-text); font-size: var(--text-sm); font-weight: var(--weight-medium); margin-bottom: var(--space-2); }

/* full-width primary CTA */
.ob-start { width: 100%; }

</style>
