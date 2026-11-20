import { defineConfig, loadEnv } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

// In development the Vite dev server plays the role Caddy plays in
// production: it proxies /api/* to the WeatherDatalogger API and injects the
// API key server-side, so the key never ends up in browser code.
// Configure in web/.env.local (never committed):
//   API_TARGET=http://192.168.1.x:8000
//   API_KEY=...
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.API_TARGET ?? 'http://localhost:8000';
  const apiKey = env.API_KEY ?? '';

  return {
    plugins: [svelte()],
    resolve: {
      alias: { $lib: fileURLToPath(new URL('./src/lib', import.meta.url)) },
    },
    server: {
      host: true,
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          ws: true,
          headers: { 'X-API-Key': apiKey },
        },
      },
    },
    build: {
      target: 'es2022',
      sourcemap: false,
    },
  };
});
