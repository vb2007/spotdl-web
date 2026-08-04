import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter()
		})
	],
	server: {
		proxy: {
			// v12: same-origin dev, mirroring production's nginx /api/ proxy
			// (frontend/nginx.conf) — see src/lib/api.ts's resolveApiBase for why. `api` is
			// the compose service name, resolvable because this dev server runs inside the
			// `web` container on the compose network (docker-compose.override.yml), not
			// directly on the host.
			'/api': {
				target: 'http://api:8000',
				changeOrigin: true
			}
		}
	}
});
