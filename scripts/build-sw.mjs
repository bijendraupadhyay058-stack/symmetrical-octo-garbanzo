// Writes public/sw.js with a unique version so every deployment updates
// installed apps (the browser re-installs a service worker whose bytes changed).
import { readFileSync, writeFileSync } from 'node:fs'

const version = (process.env.VERCEL_GIT_COMMIT_SHA || process.env.GITHUB_SHA || Date.now().toString(36)).slice(0, 12)
const src = readFileSync(new URL('./sw.template.js', import.meta.url), 'utf8').replace('__SW_VERSION__', version)
writeFileSync(new URL('../public/sw.js', import.meta.url), src)
console.log(`public/sw.js generated (version ${version})`)
