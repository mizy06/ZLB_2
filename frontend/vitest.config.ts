import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      include: [
        'test/**/*.test.ts',
        'src/lib/**/*.test.ts',
      ],
    },
  }),
);
