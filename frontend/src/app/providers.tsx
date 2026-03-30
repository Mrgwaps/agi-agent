'use client';

import React, { useEffect } from 'react';
import { ToastContainer } from '@/components/Toast';
import { useStore } from '@/lib/store';

// Triggers Zustand persist rehydration after first client render so SSR HTML
// matches the initial client render (both use default state), then updates
// in the same paint to persisted state — eliminating hydration mismatch.
function StoreHydration() {
  useEffect(() => {
    useStore.persist.rehydrate();
  }, []);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <>
      <StoreHydration />
      {children}
      <ToastContainer />
    </>
  );
}
