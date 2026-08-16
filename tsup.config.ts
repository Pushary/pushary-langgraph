import { defineConfig } from 'tsup'

export default defineConfig({
  entry: { index: 'src/index.ts' },
  format: ['esm', 'cjs'],
  dts: true,
  clean: true,
  sourcemap: true,
  external: ['@langchain/core', '@langchain/langgraph', /^@langchain\//, 'zod', '@pushary/server', /^@pushary\/server\//],
})
