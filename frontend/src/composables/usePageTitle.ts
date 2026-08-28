// apps/kimi-web/src/composables/usePageTitle.ts
// Static page title (app name only). The session title, workspace name, and
// agent activity are intentionally excluded so browser tabs and thumbnails
// remain stable.

import { computed, watchEffect, type Ref } from 'vue';
import { useI18n } from 'vue-i18n';

export interface UsePageTitleOptions {
  showAuthGate: Ref<boolean>;
}

export function usePageTitle({ showAuthGate }: UsePageTitleOptions): void {
  const { t } = useI18n();

  const pageTitle = computed<string>(() => {
    if (showAuthGate.value) return `${t('app.authPageTitle')} - TopoMind`;
    return 'TopoMind';
  });
  watchEffect(() => {
    if (typeof document !== 'undefined') document.title = pageTitle.value;
  });
}
