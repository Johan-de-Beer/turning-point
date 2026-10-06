# Dependency and asset license inventory

Generated from installed Python distribution metadata (default `.venv` plus optional
`.sdk-check` where present) and the frontend npm lockfile. Optional SDK packages do
not enter the default mock runtime.
Pinned direct versions live in `backend/requirements*.txt` and `frontend/package-lock.json`.
Preserve the corresponding upstream LICENSE/NOTICE texts when redistributing packages;
metadata alone does not complete license compliance. Packages marked unverified need review.

Application assets: fictional names, synthetic fixtures, original Blender stadium and code-built pitch geometry,
system fonts and self-hosted Barlow Condensed. No match footage, club marks, player likenesses, external font downloads,
or copyrighted music are included. Lucide icons retain their upstream ISC license. A project
source license remains the owner's choice; this inventory grants no rights beyond upstream terms.

Barlow Condensed 500/600/700 (latin subset, WOFF2) is copied from the `@fontsource/barlow-condensed` 5.3.0
npm package into `frontend/public/fonts/` and served from the app's own origin. Copyright 2017 The Barlow
Project Authors (https://github.com/jpt/barlow), SIL Open Font License 1.1; the full licence text ships
alongside the files as `frontend/public/fonts/OFL.txt`. It is not an npm dependency.

The original stadium was generated with Blender 5.2.2 LTS (GPL-3.0-or-later tool).
Blender is a development tool and is not shipped with the application. Its license does
not impose GPL on this original generated artwork. The editable `.blend`, generated
`.glb`, and reproducible script are included; see `stadium-assets.md`. Official release
source: https://download.blender.org/release/Blender5.2/.

## Python runtime and test dependencies

Optional screenshot QA uses Pillow 11.2.1 (MIT-CMU, verified from installed
distribution metadata). It is not installed in the application containers or
required for native app startup.

| Package | Version | Metadata license |
| --- | --- | --- |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| azure-ai-projects | 2.7.0 | MIT |
| azure-core | 1.41.0 | MIT |
| azure-identity | 1.26.0 | MIT |
| azure-storage-blob | 12.31.0 | MIT License |
| certifi | 2026.7.22 | MPL-2.0 |
| cffi | 2.1.1 | MIT-0 |
| charset-normalizer | 3.5.2 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| fastapi | 0.115.12 | MIT License |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpcore2 | 2.13.1 | BSD-3-Clause |
| httpx | 0.28.1 | BSD-3-Clause |
| httpx2 | 2.13.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| iniconfig | 2.3.0 | MIT |
| isodate | 0.7.2 | BSD License |
| jiter | 0.17.0 | MIT |
| msal | 1.39.0 | MIT |
| msal-extensions | 1.3.1 | MIT License |
| openai | 3.24.0 | Apache-2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pluggy | 1.6.0 | MIT |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.11.4 | MIT |
| pydantic_core | 2.33.2 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| PyJWT | 2.15.1 | MIT |
| pytest | 9.1.1 | MIT |
| requests | 2.34.2 | Apache-2.0 |
| sniffio | 1.3.1 | MIT OR Apache-2.0 |
| starlette | 0.46.2 | BSD-3-Clause |
| truststore | 0.10.4 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| urllib3 | 2.8.0 | MIT |
| uvicorn | 0.34.2 | BSD-3-Clause |

## Frontend lockfile (including platform/test/build dependencies)

| Package | Version | Metadata license |
| --- | --- | --- |
| @dimforge/rapier3d-compat | 0.12.0 | Apache-2.0 |
| @jridgewell/resolve-uri | 3.1.2 | MIT |
| @jridgewell/sourcemap-codec | 1.6.0 | MIT |
| @jridgewell/trace-mapping | 0.3.31 | MIT |
| @oxc-project/types | 0.152.0 | MIT |
| @playwright/test | 1.63.0 | Apache-2.0 |
| @rolldown/binding-android-arm-eabi | 1.2.12 | MIT |
| @rolldown/binding-android-arm64 | 1.2.12 | MIT |
| @rolldown/binding-darwin-arm64 | 1.2.12 | MIT |
| @rolldown/binding-darwin-x64 | 1.2.12 | MIT |
| @rolldown/binding-freebsd-x64 | 1.2.12 | MIT |
| @rolldown/binding-linux-arm-gnueabihf | 1.2.12 | MIT |
| @rolldown/binding-linux-arm64-gnu | 1.2.12 | MIT |
| @rolldown/binding-linux-arm64-musl | 1.2.12 | MIT |
| @rolldown/binding-linux-ppc64-gnu | 1.2.12 | MIT |
| @rolldown/binding-linux-s390x-gnu | 1.2.12 | MIT |
| @rolldown/binding-linux-x64-gnu | 1.2.12 | MIT |
| @rolldown/binding-linux-x64-musl | 1.2.12 | MIT |
| @rolldown/binding-openharmony-arm64 | 1.2.12 | MIT |
| @rolldown/binding-win32-arm64-msvc | 1.2.12 | MIT |
| @rolldown/binding-win32-x64-msvc | 1.2.12 | MIT |
| @rolldown/pluginutils | 1.0.1 | MIT |
| @tweenjs/tween.js | 23.1.3 | MIT |
| @types/chai | 5.2.3 | MIT |
| @types/deep-eql | 4.0.2 | MIT |
| @types/estree | 1.0.9 | MIT |
| @types/react | 19.3.0 | MIT |
| @types/react-dom | 19.3.0 | MIT |
| @types/stats.js | 0.17.4 | MIT |
| @types/three | 0.186.0 | MIT |
| @types/webxr | 0.5.24 | MIT |
| @typescript/typescript-aix-ppc64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-darwin-arm64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-darwin-x64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-freebsd-arm64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-freebsd-x64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-linux-arm | 7.0.2 | Apache-2.0 |
| @typescript/typescript-linux-arm64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-linux-loong64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-linux-mips64el | 7.0.2 | Apache-2.0 |
| @typescript/typescript-linux-ppc64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-linux-riscv64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-linux-s390x | 7.0.2 | Apache-2.0 |
| @typescript/typescript-linux-x64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-netbsd-arm64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-netbsd-x64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-openbsd-arm64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-openbsd-x64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-sunos-x64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-win32-arm64 | 7.0.2 | Apache-2.0 |
| @typescript/typescript-win32-x64 | 7.0.2 | Apache-2.0 |
| @vitejs/plugin-react | 6.1.2 | MIT |
| @vitest/mocker | 5.0.3 | MIT |
| @vitest/spy | 5.0.3 | MIT |
| assertion-error | 2.0.1 | MIT |
| chai | 6.3.0 | MIT |
| csstype | 3.2.3 | MIT |
| detect-libc | 2.1.2 | Apache-2.0 |
| es-module-lexer | 2.3.2 | MIT |
| estree-walker | 3.0.3 | MIT |
| expect-type | 1.4.0 | Apache-2.0 |
| fdir | 6.5.0 | MIT |
| fflate | 0.8.3 | MIT |
| fsevents | 2.3.3 | MIT |
| lightningcss | 1.33.0 | MPL-2.0 |
| lightningcss-android-arm64 | 1.33.0 | MPL-2.0 |
| lightningcss-darwin-arm64 | 1.33.0 | MPL-2.0 |
| lightningcss-darwin-x64 | 1.33.0 | MPL-2.0 |
| lightningcss-freebsd-x64 | 1.33.0 | MPL-2.0 |
| lightningcss-linux-arm-gnueabihf | 1.33.0 | MPL-2.0 |
| lightningcss-linux-arm64-gnu | 1.33.0 | MPL-2.0 |
| lightningcss-linux-arm64-musl | 1.33.0 | MPL-2.0 |
| lightningcss-linux-x64-gnu | 1.33.0 | MPL-2.0 |
| lightningcss-linux-x64-musl | 1.33.0 | MPL-2.0 |
| lightningcss-win32-arm64-msvc | 1.33.0 | MPL-2.0 |
| lightningcss-win32-x64-msvc | 1.33.0 | MPL-2.0 |
| lucide-react | 1.52.0 | ISC |
| magic-string | 1.4.3 | MIT |
| meshoptimizer | 1.1.1 | MIT |
| nanoid | 3.3.20 | MIT |
| obug | 2.2.1 | MIT |
| picocolors | 1.1.1 | ISC |
| picomatch | 4.0.7 | MIT |
| playwright | 1.63.0 | Apache-2.0 |
| playwright-core | 1.63.0 | Apache-2.0 |
| postcss | 8.5.29 | MIT |
| react | 19.3.0 | MIT |
| react-dom | 19.3.0 | MIT |
| rolldown | 1.2.12 | MIT |
| scheduler | 0.28.0 | MIT |
| source-map-js | 1.2.2 | BSD-3-Clause |
| std-env | 4.3.0 | MIT |
| three | 0.186.1 | MIT |
| tinybench | 6.2.0 | MIT |
| tinyexec | 1.3.1 | MIT |
| tinyglobby | 0.2.17 | MIT |
| typescript | 7.0.2 | Apache-2.0 |
| vite | 8.3.2 | MIT |
| vitest | 5.0.3 | MIT |
| why-is-node-running | 3.2.1 | MIT |
| zod | 4.6.5 | MIT |
