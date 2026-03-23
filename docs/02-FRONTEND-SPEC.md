# 02 — Frontend Specification

## Critical Problems in v1 Frontend

1. **`App.jsx` is a 500-line god component** — all state, all handlers, all rendering.
2. **No TypeScript** — refactors are blind; API contract changes silently break things.
3. **Prop drilling 8+ levels deep** — `onAcceptChange`, `onDenyChange`, etc. threaded through everything.
4. **`sessionStorage` for workspace** — closing tab loses all work.
5. **No routing** — entire app is a single conditional render.
6. **No server-state caching** — every navigation re-fetches.
7. **CSS files are disconnected** — no design system, inconsistent spacing/colors.
8. **No loading skeletons** — bare "Processing..." text.

---

## Stack

| Tool | Purpose |
|------|---------|
| **Vite** | Build tool (keep from v1) |
| **TypeScript (strict)** | Type safety |
| **React 19** | UI library (keep from v1) |
| **React Router v7** | Client-side routing |
| **Zustand** | Client state (auth, dataset edits, UI) |
| **TanStack Query** | Server state (API calls, caching, mutations) |
| **Tailwind CSS** | Styling |
| **Zod** | Runtime schema validation |
| **React Hook Form** | Form management |
| **`@tanstack/react-virtual`** | Virtualized table (keep from v1) |
| **`lucide-react`** | Icons (keep from v1) |
| **`idb-keyval`** | IndexedDB persistence for offline resilience |
| **`sonner`** | Toast notifications |

---

## Routing

```tsx
// src/router.tsx
import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { AuthGuard } from "@/components/auth/AuthGuard";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },               // Upload + history
      { path: "login", element: <LoginPage /> },
      { path: "register", element: <RegisterPage /> },
      {
        element: <AuthGuard />,                                   // Protected routes
        children: [
          { path: "datasets/:id", element: <AnalysisPage /> },   // Table + quality
          { path: "settings", element: <SettingsPage /> },
        ],
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
```

---

## State Architecture

### Principle: Separate client state from server state.

| State Type | Tool | Examples |
|-----------|------|----------|
| **Server state** | TanStack Query | Datasets, history, analysis results, user profile |
| **Client state** | Zustand | Current edits, undo stack, UI preferences, auth tokens |
| **Form state** | React Hook Form | Login, register, settings forms |
| **URL state** | React Router | Current page, dataset ID, query params |

### Zustand Stores

```typescript
// src/stores/authStore.ts
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

interface AuthState {
  user: User | null;
  accessToken: string | null;
  setAuth: (user: User, token: string) => void;
  clearAuth: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      setAuth: (user, accessToken) => set({ user, accessToken }),
      clearAuth: () => set({ user: null, accessToken: null }),
    }),
    {
      name: "clarifi-auth",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ accessToken: state.accessToken }),
    }
  )
);
```

```typescript
// src/stores/datasetStore.ts — Undo/Redo with Zustand middleware
import { create } from "zustand";
import { temporal } from "zundo";  // Undo middleware for Zustand

interface DatasetState {
  headers: string[];
  rows: Record<string, string>[];
  pendingChanges: Change[];
  quarantineRows: Record<string, string>[];
  activeTab: "clean" | "quarantine";
  searchQuery: string;

  setDataset: (headers: string[], rows: Record<string, string>[]) => void;
  editCell: (rowIndex: number, column: string, value: string) => void;
  setPendingChanges: (changes: Change[]) => void;
  acceptChange: (change: Change) => void;
  denyChange: (change: Change) => void;
  acceptAllChanges: () => void;
  denyAllChanges: () => void;
  setQuarantine: (rows: Record<string, string>[], headers: string[]) => void;
  mergeSelected: (indices: number[]) => void;
  mergeAll: () => void;
  setSearchQuery: (query: string) => void;
  reset: () => void;
}

export const useDatasetStore = create<DatasetState>()(
  temporal(
    (set, get) => ({
      headers: [],
      rows: [],
      pendingChanges: [],
      quarantineRows: [],
      activeTab: "clean",
      searchQuery: "",

      setDataset: (headers, rows) => set({ headers, rows, pendingChanges: [], quarantineRows: [], activeTab: "clean" }),

      editCell: (rowIndex, column, value) => {
        const rows = [...get().rows];
        rows[rowIndex] = { ...rows[rowIndex], [column]: value };
        set({ rows });
      },

      // ... other actions
      reset: () => set({
        headers: [], rows: [], pendingChanges: [],
        quarantineRows: [], activeTab: "clean", searchQuery: "",
      }),
    }),
    { limit: 50 } // Keep 50 undo steps
  )
);
```

---

## API Client

```typescript
// src/api/client.ts
import { useAuthStore } from "@/stores/authStore";

const BASE_URL = import.meta.env.VITE_API_URL || "/api/v1";

class ApiClient {
  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const token = useAuthStore.getState().accessToken;
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };

    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";

    const response = await fetch(`${BASE_URL}${path}`, { ...options, headers, credentials: "include" });

    if (response.status === 401) {
      // Attempt silent refresh
      const refreshed = await this.refreshToken();
      if (refreshed) return this.request<T>(path, options); // Retry
      useAuthStore.getState().clearAuth();
      window.location.href = "/login";
      throw new Error("Session expired");
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: "Unknown error" }));
      throw new ApiError(response.status, error.detail || error.error);
    }

    return response.json();
  }

  private async refreshToken(): Promise<boolean> {
    try {
      const res = await fetch(`${BASE_URL}/auth/refresh`, { method: "POST", credentials: "include" });
      if (!res.ok) return false;
      const { access_token } = await res.json();
      useAuthStore.getState().setAuth(useAuthStore.getState().user!, access_token);
      return true;
    } catch {
      return false;
    }
  }

  get<T>(path: string) { return this.request<T>(path); }
  post<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: "POST",
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
  }
  delete<T>(path: string) { return this.request<T>(path, { method: "DELETE" }); }
}

export const api = new ApiClient();
```

---

## TanStack Query Hooks

```typescript
// src/hooks/useDataset.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useDatasetStore } from "@/stores/datasetStore";

export function useAnalyzeDataset() {
  const queryClient = useQueryClient();
  const setDataset = useDatasetStore((s) => s.setDataset);

  return useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);

      // 1. Upload + parse
      const parsed = await api.post<ParseResponse>("/datasets/parse", fd);

      // 2. Trigger async analysis job
      const job = await api.post<JobResponse>("/datasets/analyze", fd);

      return { parsed, jobId: job.id };
    },
    onSuccess: ({ parsed }) => {
      setDataset(parsed.headers, parsed.rows);
    },
  });
}

export function useDatasetHistory() {
  return useQuery({
    queryKey: ["history"],
    queryFn: () => api.get<HistoryEntry[]>("/history"),
    staleTime: 30_000, // 30s cache
  });
}

export function useDeleteHistoryItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/history/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["history"] }),
  });
}
```

---

## WebSocket Hook for Job Progress

```typescript
// src/hooks/useJobProgress.ts
import { useState, useEffect, useCallback } from "react";

interface JobProgress {
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  message?: string;
  error?: string;
}

export function useJobProgress(jobId: string | null) {
  const [progress, setProgress] = useState<JobProgress>({ status: "pending", progress: 0 });

  useEffect(() => {
    if (!jobId) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/v1/jobs/ws/${jobId}`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data) as JobProgress;
      setProgress(data);
    };

    ws.onerror = () => setProgress((p) => ({ ...p, status: "failed", error: "Connection lost" }));
    ws.onclose = () => {}; // Normal close on job completion

    return () => ws.close();
  }, [jobId]);

  return progress;
}
```

---

## Component Architecture

### Layout Components

```
AppShell
├── Topbar (logo, user menu, nav)
├── Outlet (page content from router)
└── Toaster (sonner notifications)
```

### Dashboard Page

```
DashboardPage
├── HistorySidebar (if authenticated)
│   ├── HistoryItem (click to load)
│   └── DeleteButton
├── UploadZone (drag & drop)
│   └── FileDropArea
└── ProgressOverlay (if uploading)
    └── ProgressBar
```

### Analysis Page (replaces v1's inline `step === 'preview'`)

```
AnalysisPage
├── AnalysisTopbar
│   ├── BackButton
│   ├── Title
│   ├── SearchBar
│   ├── UndoRedoButtons
│   ├── AutoFixButton
│   ├── ReAnalyzeButton
│   ├── SaveButton
│   └── ExportDropdown
├── SheetTabs (Clean | Quarantine)
├── TableArea
│   ├── DataTable (virtualized)
│   │   ├── ColumnHeader (sortable, filterable)
│   │   └── DataCell (editable, change overlay)
│   └── QuarantineTable (separate component)
└── QualitySidebar
    ├── DatasetMeta
    ├── ScoreRing
    ├── CategoryBars (collapsible)
    ├── PendingChangesCard
    ├── ImpactCard
    ├── AnomaliesCard
    ├── SummaryCard
    └── IssueNavigator
```

### Key UI Component: DataCell

The most complex component — handles display, edit, and change overlay states.

```tsx
// src/components/dataset/DataCell.tsx
interface DataCellProps {
  value: string;
  rowIndex: number;
  column: string;
  change?: Change;
  issueSeverity?: "critical" | "warning" | "info";
  onEdit: (value: string) => void;
  onAcceptChange?: () => void;
  onDenyChange?: () => void;
}

function DataCell({ value, change, issueSeverity, onEdit, onAcceptChange, onDenyChange }: DataCellProps) {
  const [isEditing, setIsEditing] = useState(false);

  if (change) {
    return <ChangeOverlay change={change} onAccept={onAcceptChange} onDeny={onDenyChange} />;
  }

  if (isEditing) {
    return (
      <input
        autoFocus
        defaultValue={value}
        onBlur={(e) => { onEdit(e.target.value); setIsEditing(false); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") { onEdit(e.currentTarget.value); setIsEditing(false); }
          if (e.key === "Escape") setIsEditing(false);
        }}
        className="w-full bg-transparent border-none outline-none text-inherit"
      />
    );
  }

  return (
    <div
      onDoubleClick={() => setIsEditing(true)}
      className={cn(
        "truncate cursor-default",
        issueSeverity === "critical" && "bg-red-500/10",
        issueSeverity === "warning" && "bg-amber-500/10",
        issueSeverity === "info" && "bg-cyan-500/10",
      )}
    >
      {value}
      {issueSeverity && <IssueBadge severity={issueSeverity} />}
    </div>
  );
}
```

---

## Tailwind Configuration

```typescript
// tailwind.config.ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          primary: "#0a0f1a",
          secondary: "#111827",
          card: "#0d1526",
          elevated: "#1e293b",
        },
        accent: {
          blue: "#3b82f6",
          purple: "#8b5cf6",
          green: "#10b981",
          amber: "#f59e0b",
          red: "#ef4444",
          cyan: "#06b6d4",
        },
        text: {
          primary: "#e2e8f0",
          secondary: "#94a3b8",
          muted: "#64748b",
          faint: "#475569",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
```

---

## TypeScript Types (Generated from OpenAPI)

```typescript
// src/types/api.ts — auto-generated or manually maintained from backend schemas

export interface User {
  id: string;
  email: string;
  username: string;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: User;
  access_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface ParseResponse {
  headers: string[];
  rows: Record<string, string>[];
}

export interface QualityReport {
  dataset_meta: DatasetMeta;
  overall_quality_score: number;
  executive_summary: string;
  category_breakdown: CategoryBreakdown;
  issues: Issue[];
}

export interface Issue {
  inspector_name: string;
  category: "completeness" | "uniqueness" | "consistency" | "accuracy" | "format";
  column: string[];
  severity: "critical" | "warning" | "info";
  count: number;
  description: string;
  suggestion: string | null;
  affected_cells: AffectedCell[];
}

export interface Change {
  row: number;
  column: string;
  old_value: string;
  new_value: string;
  kind: "fixed" | "warning" | "critical";
  reason: string;
}

export interface JobResponse {
  id: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
}

export interface HistoryEntry {
  id: string;
  filename: string;
  original_format: string;
  row_count: number | null;
  column_count: number | null;
  quality_score_before: number | null;
  quality_score_after: number | null;
  created_at: string;
}
```

---

## `package.json`

```json
{
  "name": "clarifi-frontend",
  "private": true,
  "version": "2.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext .ts,.tsx",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^19.2.0",
    "react-dom": "^19.2.0",
    "react-router-dom": "^7.0.0",
    "@tanstack/react-query": "^5.60.0",
    "@tanstack/react-virtual": "^3.13.0",
    "zustand": "^5.0.0",
    "zundo": "^2.3.0",
    "zod": "^3.23.0",
    "react-hook-form": "^7.54.0",
    "@hookform/resolvers": "^3.9.0",
    "lucide-react": "^0.575.0",
    "sonner": "^1.7.0",
    "idb-keyval": "^6.2.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.6.0"
  },
  "devDependencies": {
    "@types/react": "^19.2.0",
    "@types/react-dom": "^19.2.0",
    "@vitejs/plugin-react": "^5.1.0",
    "typescript": "^5.7.0",
    "vite": "^7.3.0",
    "tailwindcss": "^4.0.0",
    "eslint": "^9.39.0",
    "eslint-plugin-react-hooks": "^7.0.0",
    "eslint-plugin-react-refresh": "^0.4.0",
    "@typescript-eslint/eslint-plugin": "^8.0.0",
    "@typescript-eslint/parser": "^8.0.0"
  }
}
```
