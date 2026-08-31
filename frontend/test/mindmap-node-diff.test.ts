import { describe, expect, it } from 'vitest';

import {
  MindmapNodeStreamTracker,
  mindmapNodeMap,
} from '../src/api/mindmapNodeDiff';

describe('MindmapNodeStreamTracker', () => {
  it('extracts complete nodes across arbitrary stream boundaries', () => {
    const tracker = new MindmapNodeStreamTracker();

    expect(tracker.push('{"title":"课程","no')).toEqual([]);
    expect(tracker.push('des":[{"id":"root","name":"根')).toEqual([]);
    expect(tracker.push('节点","meta":{"note":"含有 } 和 \\" 引号"}}')).toEqual([
      { id: 'root', name: '根节点' },
    ]);
    expect(tracker.push(',{"id":"child","name":"子节点"}],"edges":[]')).toEqual([
      { id: 'child', name: '子节点' },
    ]);
    expect(tracker.complete).toBe(true);
  });

  it('ignores other arrays and accepts name as a stable fallback', () => {
    const tracker = new MindmapNodeStreamTracker();

    expect(
      tracker.push(
        '{"issues":[{"name":"不是节点"}],"nodes":[{"name":"无显式 ID"}]}',
      ),
    ).toEqual([{ id: '无显式 ID', name: '无显式 ID' }]);
  });
});

describe('mindmapNodeMap', () => {
  it('normalizes persisted graph nodes into id-to-name baselines', () => {
    expect(
      [...mindmapNodeMap([
        { id: 'root', name: '根节点' },
        { id: 'child' },
        null,
      ])],
    ).toEqual([
      ['root', '根节点'],
      ['child', 'child'],
    ]);
  });
});
