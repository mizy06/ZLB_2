<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue';
import Button from './ui/Button.vue';
import Input from './ui/Input.vue';
import { getKimiWebApi } from '../api';

type AuthMode = 'login' | 'register';

const mode = ref<AuthMode>('login');
const username = ref('');
const password = ref('');
const submitting = ref(false);
const errorMessage = ref('');
const usernameRef = ref<InstanceType<typeof Input> | null>(null);

const title = () => mode.value === 'login' ? '登录 TopoMind' : '注册 TopoMind';

onMounted(() => {
  void nextTick(() => usernameRef.value?.focus());
});

function switchMode(next: AuthMode): void {
  if (submitting.value) return;
  mode.value = next;
  errorMessage.value = '';
}

async function submit(): Promise<void> {
  if (submitting.value) return;
  errorMessage.value = '';
  submitting.value = true;
  try {
    const api = getKimiWebApi();
    if (mode.value === 'register') {
      if (!api.registerAccount) {
        throw new Error('当前服务不支持本地账号注册。');
      }
      await api.registerAccount({
        username: username.value,
        password: password.value,
      });
    } else {
      if (!api.loginAccount) {
        throw new Error('当前服务不支持本地账号登录。');
      }
      await api.loginAccount({
        username: username.value,
        password: password.value,
      });
    }
    // The HttpOnly cookie is now set. Reload the complete client so no state
    // from the unauthenticated attempt can survive into the new account.
    window.location.reload();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败，请稍后重试。';
  } finally {
    submitting.value = false;
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter') {
    event.preventDefault();
    void submit();
  }
}
</script>

<template>
  <div class="account-auth-overlay" role="dialog" aria-modal="true" aria-labelledby="account-auth-title">
    <div class="account-auth-card">
      <div class="account-auth-head">
        <h1 id="account-auth-title" class="account-auth-title">{{ title() }}</h1>
        <p class="account-auth-hint">
          {{ mode === 'login' ? '登录后只能看到你自己的会话和思维导图。' : '创建一个独立账号，开始使用你的专属会话空间。' }}
        </p>
      </div>

      <div class="account-auth-tabs" role="tablist" aria-label="账号操作">
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'login'"
          :class="{ active: mode === 'login' }"
          @click="switchMode('login')"
        >
          登录
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="mode === 'register'"
          :class="{ active: mode === 'register' }"
          @click="switchMode('register')"
        >
          注册
        </button>
      </div>

      <form class="account-auth-body" @submit.prevent="submit">
        <Input
          ref="usernameRef"
          v-model="username"
          autocomplete="username"
          placeholder="用户名"
          :disabled="submitting"
        />
        <Input
          v-model="password"
          type="password"
          autocomplete="current-password"
          placeholder="密码（至少 8 位）"
          :disabled="submitting"
          @keydown="onKeydown"
        />
        <p v-if="errorMessage" class="account-auth-error" role="alert">{{ errorMessage }}</p>
        <div class="account-auth-foot">
          <Button
            type="submit"
            variant="primary"
            :disabled="!username || !password || submitting"
            :loading="submitting"
          >
            {{ submitting ? '处理中…' : mode === 'login' ? '登录' : '注册并进入' }}
          </Button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.account-auth-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-max);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: color-mix(in srgb, var(--color-bg) 78%, transparent);
}

.account-auth-card {
  width: 440px;
  max-width: 100%;
  overflow: hidden;
  color: var(--color-text);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-xl);
  font-family: var(--font-ui);
}

.account-auth-head {
  padding: 22px 24px 14px;
}

.account-auth-title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-medium);
}

.account-auth-hint {
  margin: 6px 0 0;
  color: var(--color-text-muted);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
}

.account-auth-tabs {
  display: flex;
  gap: 4px;
  padding: 0 24px;
  border-bottom: 1px solid var(--color-line);
}

.account-auth-tabs button {
  padding: 9px 4px 10px;
  color: var(--color-text-muted);
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  font: inherit;
}

.account-auth-tabs button.active {
  color: var(--color-text);
  border-bottom-color: var(--color-accent);
}

.account-auth-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 22px 24px 24px;
}

.account-auth-error {
  margin: -2px 0 0;
  color: var(--color-danger);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
}

.account-auth-foot {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}
</style>
