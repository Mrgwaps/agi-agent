import dynamic from 'next/dynamic';

// Disable SSR entirely for the app shell — it reads localStorage/zustand
// persisted state and uses browser APIs, making it purely client-side.
// This eliminates all React hydration mismatches permanently.
const AppClient = dynamic(() => import('@/components/AppClient'), {
  ssr: false,
  loading: () => (
    <div className="neural-bg flex items-center justify-center h-screen">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        <p className="text-xs text-text-muted">Loading…</p>
      </div>
    </div>
  ),
});

export default function Page() {
  return <AppClient />;
}
