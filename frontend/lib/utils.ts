import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function fmt$$(n: number | null | undefined, decimals = 0): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

export function fmtNum(n: number | null | undefined, decimals = 0): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

export function fmtPct(n: number | null | undefined, decimals = 1): string {
  if (n == null) return "—";
  return `${n.toFixed(decimals)}%`;
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function pacingLabel(rate: number): { label: string; color: string } {
  if (rate > 1.2) return { label: "Over-pacing", color: "text-red-400" };
  if (rate > 1.05) return { label: "Slightly over", color: "text-orange-400" };
  if (rate >= 0.95) return { label: "On track", color: "text-green-400" };
  if (rate >= 0.75) return { label: "Under-pacing", color: "text-yellow-400" };
  if (rate > 0) return { label: "Severe under", color: "text-red-500" };
  return { label: "Paused", color: "text-slate-400" };
}

export function statusColor(status: string): string {
  switch (status) {
    case "active": return "text-green-400 bg-green-400/10";
    case "paused": return "text-slate-400 bg-slate-400/10";
    case "completed": return "text-green-400 bg-green-400/10";
    case "pending_approval": return "text-yellow-400 bg-yellow-400/10";
    case "rejected": return "text-red-400 bg-red-400/10";
    case "rolled_back": return "text-orange-400 bg-orange-400/10";
    case "dry_run": return "text-blue-400 bg-blue-400/10";
    case "failed": return "text-red-500 bg-red-500/10";
    case "running": return "text-blue-400 bg-blue-400/10";
    default: return "text-slate-400 bg-slate-400/10";
  }
}

export function actionIcon(actionType: string): string {
  switch (actionType) {
    case "update_bid_modifier": return "⚡";
    case "update_budget": return "💰";
    case "pause_campaign": return "⏸";
    case "update_targeting": return "🎯";
    case "update_supply_sources": return "🏗";
    case "route_creative": return "🎨";
    default: return "🔧";
  }
}

export function relTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
