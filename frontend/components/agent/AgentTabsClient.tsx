"use client";

import { useState } from "react";
import { AgentConsole } from "./AgentConsole";
import WorkflowConsole from "./WorkflowConsole";
import type { Campaign } from "@/lib/types";

type Tab = "workflow" | "classic";

export default function AgentTabsClient({ campaigns }: { campaigns: Campaign[] }) {
  const [tab, setTab] = useState<Tab>("workflow");

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="flex gap-1 px-6 pt-3 border-b border-gray-800">
        {(["workflow", "classic"] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium rounded-t border-b-2 transition-colors ${
              tab === t
                ? "border-indigo-500 text-indigo-300 bg-indigo-950/40"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {t === "workflow" ? "Multi-Agent Workflow" : "Classic Agent"}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-hidden p-6">
        {tab === "workflow" ? (
          <WorkflowConsole />
        ) : (
          <AgentConsole campaigns={campaigns} />
        )}
      </div>
    </div>
  );
}
