'use client';

import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react';
import { useStore } from '@/lib/store';
import { cn } from '@/lib/utils';
import type { Toast } from '@/lib/types';

const ICONS = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const COLORS = {
  success: 'border-success/30 bg-success/10 text-success',
  error: 'border-error/30 bg-error/10 text-error',
  warning: 'border-warning/30 bg-warning/10 text-warning',
  info: 'border-primary/30 bg-primary/10 text-accent',
};

const DEFAULT_DURATION = 5000;

function ToastItem({ toast }: { toast: Toast }) {
  const removeToast = useStore((s) => s.removeToast);
  const Icon = ICONS[toast.type];
  const duration = toast.duration === 0 ? null : (toast.duration ?? DEFAULT_DURATION);

  useEffect(() => {
    if (!duration) return;
    const t = setTimeout(() => removeToast(toast.id), duration);
    return () => clearTimeout(t);
  }, [toast.id, duration, removeToast]);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 48, scale: 0.95 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      exit={{ opacity: 0, x: 48, scale: 0.95 }}
      transition={{ type: 'spring', stiffness: 400, damping: 30 }}
      className={cn(
        'relative flex items-start gap-3 p-4 rounded-xl border glass-card',
        'w-80 max-w-full shadow-card pointer-events-auto',
        COLORS[toast.type]
      )}
    >
      <Icon className="w-5 h-5 mt-0.5 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold leading-tight">{toast.title}</p>
        {toast.message && (
          <p className="text-xs mt-1 opacity-80 leading-relaxed text-text-muted">
            {toast.message}
          </p>
        )}
      </div>
      <button
        onClick={() => removeToast(toast.id)}
        className="flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity p-0.5 rounded"
        aria-label="Dismiss"
      >
        <X className="w-4 h-4" />
      </button>
      {duration && (
        <motion.div
          className="absolute bottom-0 left-0 h-0.5 rounded-b-xl opacity-40"
          style={{ background: 'currentColor' }}
          initial={{ width: '100%' }}
          animate={{ width: '0%' }}
          transition={{ duration: duration / 1000, ease: 'linear' }}
        />
      )}
    </motion.div>
  );
}

export function ToastContainer() {
  const toasts = useStore((s) => s.toasts);

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none"
      aria-live="polite"
      aria-atomic="false"
    >
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} />
        ))}
      </AnimatePresence>
    </div>
  );
}
