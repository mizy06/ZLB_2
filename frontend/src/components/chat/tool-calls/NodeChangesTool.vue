<script setup lang="ts">
import { computed, ref } from 'vue';
import type {
  DiffViewLine,
  FilePreviewRequest,
  ToolCall,
  ToolMedia,
} from '../../../types';
import { toolGlyph } from '../../../lib/toolMeta';
import DiffLines from '../DiffLines.vue';
import ToolRow from '../ToolRow.vue';

const props = withDefaults(
  defineProps<{
    tool: ToolCall;
    mobile?: boolean;
    stackPosition?: 'single' | 'first' | 'middle' | 'last';
    toolDiffPanel?: boolean;
  }>(),
  { mobile: false, stackPosition: 'single', toolDiffPanel: false },
);

defineEmits<{
  openMedia: [media: ToolMedia];
  openFile: [target: FilePreviewRequest];
  openToolDiff: [id: string];
}>();

const open = ref(true);
const icon = toolGlyph('edit');
const changes = computed<DiffViewLine[]>(() => {
  const result: DiffViewLine[] = [];
  for (const line of props.tool.output ?? []) {
    if (line.startsWith('+ ')) {
      result.push({ type: 'add', text: line.slice(2) });
    } else if (line.startsWith('- ')) {
      result.push({ type: 'del', text: line.slice(2) });
    }
  }
  return result;
});
const additions = computed(
  () => changes.value.filter((line) => line.type === 'add').length,
);
const deletions = computed(
  () => changes.value.filter((line) => line.type === 'del').length,
);
const summary = computed(() => {
  if (changes.value.length === 0) {
    return props.tool.status === 'running' ? '等待节点输出' : '无节点变更';
  }
  return `+${additions.value} / -${deletions.value}`;
});
</script>

<template>
  <ToolRow
    :status="tool.status"
    :icon="icon"
    name="节点变更"
    :arg="summary"
    :open="open"
    expandable
    :stacked="stackPosition !== 'single'"
    :stack-position="stackPosition"
    @toggle="open = !open"
  >
    <div v-if="changes.length === 0" class="node-diff-empty">
      {{ tool.status === 'running' ? '等待节点输出…' : '本轮没有节点增减' }}
    </div>
    <div v-else class="node-diff-lines">
      <DiffLines :lines="changes" compact />
    </div>
  </ToolRow>
</template>

<style scoped>
.node-diff-empty {
  color: var(--color-text-muted);
}

.node-diff-lines {
  max-height: min(320px, 42vh);
  overflow: auto;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-sm);
  background: var(--color-surface-raised);
}
</style>
