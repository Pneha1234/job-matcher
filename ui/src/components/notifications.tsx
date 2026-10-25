"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { apiGet, type SettingsResponse } from "@/lib/api";

const SEEN_KEY = "jm-notified-since";

type Match = { id: number; title: string; company: string; pct: number; scored_at: string };

/** The desktop app (Tauri) exposes native notifications; a browser tab uses the web API. */
type NativeNotifications = {
  isPermissionGranted: () => Promise<boolean>;
  requestPermission: () => Promise<string>;
  sendNotification: (options: { title: string; body?: string }) => void;
};

export function nativeNotifications(): NativeNotifications | null {
  if (typeof window === "undefined") return null;
  const tauri = (window as unknown as { __TAURI__?: { notification?: NativeNotifications } }).__TAURI__;
  return tauri?.notification ?? null;
}

function readSince(): string {
  try {
    return localStorage.getItem(SEEN_KEY) ?? new Date().toISOString();
  } catch {
    return new Date().toISOString();
  }
}

function writeSince(value: string) {
  try {
    localStorage.setItem(SEEN_KEY, value);
  } catch {
    // Without storage, this visit still notifies; the next one starts from "now".
  }
}

/** Desktop notifications for new strong matches while the app is open in a tab. */
export function NotificationWatcher() {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => apiGet<SettingsResponse>("/settings") });
  const enabled = !!data?.settings.notify;
  const router = useRouter();

  useEffect(() => {
    const native = nativeNotifications();
    if (!enabled || (!native && typeof Notification === "undefined")) return;
    let since = readSince();
    writeSince(since);
    async function allowed(): Promise<boolean> {
      if (native) return (await native.isPermissionGranted()) || (await native.requestPermission()) === "granted";
      return Notification.permission === "granted";
    }
    async function poll() {
      if (!(await allowed())) return;
      const now = new Date().toISOString();
      const matches = await apiGet<Match[]>(`/notifications?since=${encodeURIComponent(since)}`).catch(() => []);
      since = now;
      writeSince(now);
      if (native) {
        // Native notifications can't carry a click handler here; the digest lists them.
        for (const m of matches.slice(0, 3)) native.sendNotification({ title: `${Math.round(m.pct)}% match: ${m.title}`, body: m.company });
        if (matches.length > 3) native.sendNotification({ title: `${matches.length - 3} more strong matches` });
        return;
      }
      for (const m of matches.slice(0, 3)) {
        const n = new Notification(`${Math.round(m.pct)}% match: ${m.title}`, { body: m.company, tag: `job-${m.id}` });
        n.onclick = () => {
          window.focus();
          router.push(`/jobs?job=${m.id}`);
        };
      }
      if (matches.length > 3) {
        new Notification(`${matches.length - 3} more strong matches`, { body: "Open Job Matcher to see them", tag: "more" });
      }
    }
    const timer = setInterval(poll, 60_000);
    poll();
    return () => clearInterval(timer);
  }, [enabled, router]);

  return null;
}
