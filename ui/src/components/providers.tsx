"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { NotificationWatcher } from "@/components/notifications";
import { ToastProvider } from "@/components/toast";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 10_000 } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <NotificationWatcher />
        {children}
      </ToastProvider>
    </QueryClientProvider>
  );
}
