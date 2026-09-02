'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useState, type ReactNode } from 'react';
import { Toaster } from 'react-hot-toast';

import { NotificationProvider } from '@/lib/notifications';

/**
 * Root providers wrapper.
 *
 * Provides:
 *  - React Query context (data fetching + caching)
 *  - WebSocket NotificationProvider (real-time alerts + trace progress)
 *  - react-hot-toast for in-app toast messages
 *
 * Requirements: 13.1, 18.6
 */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,          // 30 seconds
            gcTime: 5 * 60 * 1000,      // 5 minutes
            retry: 1,
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: 0,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <NotificationProvider>
        {children}
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            style: {
              background: '#1f2937',
              color: '#f9fafb',
            },
          }}
        />
        {process.env.NODE_ENV === 'development' && (
          <ReactQueryDevtools initialIsOpen={false} />
        )}
      </NotificationProvider>
    </QueryClientProvider>
  );
}
