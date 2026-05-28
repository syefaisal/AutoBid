"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Megaphone,
  Bot,
  ClipboardList,
  FlaskConical,
  Activity,
  Zap,
} from "lucide-react";

const nav = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/campaigns", label: "Campaigns", icon: Megaphone },
  { href: "/agent", label: "Agent Console", icon: Bot },
  { href: "/audit", label: "Audit Log", icon: ClipboardList },
  { href: "/experiments", label: "Experiments", icon: FlaskConical },
  { href: "/traces", label: "Traces", icon: Activity },
];

export function Sidebar() {
  const path = usePathname();

  return (
    <aside className="w-56 shrink-0 flex flex-col bg-[#111827] border-r border-gray-800 h-full">
      <div className="px-4 py-5 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="font-bold text-sm text-white tracking-tight">AutoBid</p>
            <p className="text-[10px] text-gray-500">AI Control Plane</p>
          </div>
        </div>
      </div>

      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {nav.map(({ href, label, icon: Icon }) => {
          const active = path === href || (href !== "/" && path.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors",
                active
                  ? "bg-violet-600/20 text-violet-300 font-medium"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-800"
              )}
            >
              <Icon className={cn("w-4 h-4", active ? "text-violet-400" : "text-gray-500")} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="px-4 py-3 border-t border-gray-800">
        <p className="text-[10px] text-gray-600 leading-relaxed">
          claude-sonnet-4-6 · RAG · Tool Use · Observability
        </p>
      </div>
    </aside>
  );
}
