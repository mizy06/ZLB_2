import { describe, expect, it } from 'vitest';
import { nextTick, ref, type Ref } from 'vue';
import type { AppSkill } from '../src/api/types';
import { useSlashMenu } from '../src/composables/useSlashMenu';
import { buildSlashItems, isRemovedSlashCommand } from '../src/lib/slashCommands';

// Public slash-menu contract: matching built-ins and dispatching selected
// commands without coupling tests to component internals.

interface MockTextarea {
  value: string;
  selectionStart: number;
  setSelectionRange: (start: number, end: number) => void;
  focus: () => void;
}

function setup(initialText = '', skills: AppSkill[] = []) {
  const textarea: MockTextarea = {
    value: initialText,
    selectionStart: 0,
    setSelectionRange(start: number) {
      this.selectionStart = start;
    },
    focus: () => {},
  };
  const text = ref(initialText);
  const textareaRef = ref(textarea as unknown as HTMLTextAreaElement) as Ref<HTMLTextAreaElement | null>;
  const emitted: string[] = [];
  const pushed: string[] = [];
  const slash = useSlashMenu({
    text,
    textareaRef,
    autosize: () => {},
    skills: () => skills,
    emitCommand: (cmd) => emitted.push(cmd),
    historyPush: (entry) => pushed.push(entry),
  });
  return { text, textarea, emitted, pushed, slash };
}

describe('useSlashMenu — update', () => {
  it('stays closed for empty text', () => {
    const { slash } = setup('');
    slash.update();
    expect(slash.open.value).toBe(false);
  });

  it('opens and lists commands for a lone slash', () => {
    const { slash } = setup('/');
    slash.update();
    expect(slash.open.value).toBe(true);
    expect(slash.items.value.length).toBeGreaterThan(0);
    expect(slash.active.value).toBe(0);
  });

  it('filters to matching commands', () => {
    const { slash } = setup('/com');
    slash.update();
    expect(slash.open.value).toBe(true);
    expect(slash.items.value.map((i) => i.name)).toContain('/compact');
  });

  it('does not expose removed slash commands', () => {
    const names = buildSlashItems().map((item) => item.name);
    expect(names).not.toEqual(expect.arrayContaining(['/fork', '/undo', '/thinking', '/btw', '/goal', '/clear']));
  });

  it('reserves removed names from session skills too', () => {
    const names = buildSlashItems([
      { name: 'goal', description: 'custom goal skill', source: 'project' },
      { name: 'undo', description: 'custom undo skill', source: 'builtin' },
      { name: 'deploy', description: 'deploy stuff', source: 'project' },
    ]).map((item) => item.name);
    expect(names).not.toContain('/skill:goal');
    expect(names).not.toContain('/undo');
    expect(names).toContain('/skill:deploy');
  });

  it('marks removed commands so hand-typed input cannot activate them', () => {
    expect(isRemovedSlashCommand('/GOAL')).toBe(true);
    expect(isRemovedSlashCommand('/swarm')).toBe(false);
  });

  it('offers the session export command for an export prefix', () => {
    const { slash } = setup('/exp');
    slash.update();
    expect(slash.items.value.map((item) => item.name)).toContain('/export');
  });

  it('closes when nothing matches', () => {
    const { slash } = setup('/zzzznotacommand');
    slash.update();
    expect(slash.open.value).toBe(false);
  });

  it('closes once the token contains a space', () => {
    const { slash } = setup('/swarm some task');
    slash.update();
    expect(slash.open.value).toBe(false);
  });

  it('closes for text that does not start with a slash', () => {
    const { slash } = setup('hello');
    slash.update();
    expect(slash.open.value).toBe(false);
  });

  it('includes session skills as /skill:<skill-name>', () => {
    const { slash } = setup('/', [{ name: 'deploy', description: 'deploy stuff', source: 'project' } as AppSkill]);
    slash.update();
    const names = slash.items.value.map((i) => i.name);
    expect(names).toContain('/skill:deploy');
  });

  it('keeps builtin-sourced skills unprefixed', () => {
    const { slash } = setup('/', [{ name: 'update-config', description: 'edit config', source: 'builtin' } as AppSkill]);
    slash.update();
    const names = slash.items.value.map((i) => i.name);
    expect(names).toContain('/update-config');
    expect(names).not.toContain('/skill:update-config');
  });

  it('matches a prefixed skill when filtering by its bare name', () => {
    const { slash } = setup('/depl', [{ name: 'deploy', description: 'deploy stuff', source: 'project' } as AppSkill]);
    slash.update();
    expect(slash.items.value.map((i) => i.name)).toContain('/skill:deploy');
  });
});

describe('useSlashMenu — select', () => {
  it('non-acceptsInput: clears text, pushes history, emits the command', () => {
    const { text, emitted, pushed, slash } = setup('/new');
    slash.select({ name: '/new', desc: '' });
    expect(text.value).toBe('');
    expect(pushed).toEqual(['/new']);
    expect(emitted).toEqual(['/new']);
    expect(slash.open.value).toBe(false);
  });

  it('acceptsInput: keeps the command in the box and does not emit yet', async () => {
    const { text, emitted, pushed, slash } = setup('/swarm');
    slash.select({ name: '/swarm', desc: '', acceptsInput: true });
    expect(text.value).toBe('/swarm ');
    expect(emitted).toEqual([]);
    expect(pushed).toEqual([]);
    expect(slash.open.value).toBe(false);
    await nextTick();
  });
});
