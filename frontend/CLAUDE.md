# Frontend context

## State rules
- useQuery / useMutation for anything from the API (never useState for server data)
- Zustand stores: authStore (user/tokens), datasetStore (current dataset + edits + undo), uiStore (modals/sidebar)
- Never pass store state as props more than 1 level deep — use the hook directly

## Component structure
- components/ui/ — primitives only (Button, Input, Modal, Badge) — no business logic
- components/dataset/ — DataTable must use @tanstack/react-virtual for >200 rows
- All API calls go through api/ modules — no fetch() calls in components

## TypeScript rules
- Types in types/api.ts are generated from OpenAPI — don't hand-edit them
- Zod schemas for all form inputs (React Hook Form + Zod resolver)
- No `as SomeType` casting — use type guards

## WebSocket pattern (job progress)
Use hooks/useJobProgress.ts — don't create new WS connections directly