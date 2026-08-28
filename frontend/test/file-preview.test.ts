import { describe, expect, it } from 'vitest';
import { isPlayableMediaUrl } from '../src/composables/useFilePreview';

describe('isPlayableMediaUrl', () => {
  it.each([
    'https://example.com/image.png',
    'blob:https://example.com/id',
    'data:image/png;base64,AA==',
    '/api/jobs/task/export.png',
    './preview.png',
    'preview.png',
  ])('accepts browser-loadable media URL %s', (url) => {
    expect(isPlayableMediaUrl(url)).toBe(true);
  });

  it.each(['', '   ', 'ms://provider/file', 'file:///tmp/image.png'])(
    'rejects unsupported media URL %s',
    (url) => {
      expect(isPlayableMediaUrl(url)).toBe(false);
    },
  );
});
