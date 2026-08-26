# TopoMind Web UI Adoption

## Scope

The frontend uses the official Vue 3 web application formerly shipped in the
public `MoonshotAI/kimi-code` repository as its UI baseline. The adopted source
comes from commit `c32e661faa931df9fdc72e63230f3ebebc00dce5`, immediately
before the source tree was removed from that repository by
[`MoonshotAI/kimi-code#2599`](https://github.com/MoonshotAI/kimi-code/pull/2599).

The component tree, design tokens, responsive shell, conversation rendering,
composer, settings, file preview, animations, and upstream tests remain in
their original Vue architecture. The active entry point is `src/main.ts` and
`src/App.vue`; the older React prototype is not part of the build.

## Local Adaptation

The user-facing product is branded as `拓知 TopoMind`. The five-node mind-tree
mark is implemented once in `frontend/src/components/BrandMark.vue`, with
light/dark brand tokens and matching favicon, touch icon, and static SVG assets
under `frontend/public/`. Page titles, onboarding, notifications, provider
labels, settings, and the default workspace use the same product name.

Execution approval, permission-mode, and automatic-approval controls are not
rendered. Question cards remain available for future language interaction.

`src/api/mindmapAgent.ts` implements the existing web API boundary over the
project's current endpoints:

- `GET /api/history`
- `POST /api/jobs`
- `GET /api/jobs/{id}`
- `GET /api/jobs/{id}/events`
- `POST /api/jobs/{id}/cancel`
- `GET /api/jobs/{id}/export.png`

Pipeline stages and model calls are projected into compact, collapsible action
rows. Completed mind maps appear as constrained conversation thumbnails and
open the original export in the right-side high-resolution preview.

Internal upstream-compatible symbol names, protocol types, storage keys, and
source attribution remain where changing them would create unnecessary
compatibility drift. They are not exposed as product branding.

## License

The adopted upstream source is distributed under the
[`MIT License`](https://github.com/MoonshotAI/kimi-code/blob/c32e661faa931df9fdc72e63230f3ebebc00dce5/LICENSE).
The upstream copyright and license terms must remain with redistributed source.
