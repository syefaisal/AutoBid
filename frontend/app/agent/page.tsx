import { AgentConsole } from "@/components/agent/AgentConsole";
import WorkflowConsole from "@/components/agent/WorkflowConsole";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AgentPage() {
  let campaigns: Awaited<ReturnType<typeof api.campaigns.list>> = [];
  try {
    campaigns = await api.campaigns.list();
  } catch {}

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-4 border-b border-gray-800">
        <h1 className="text-xl font-bold text-white">Agent Console</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Multi-agent LangGraph workflow · RAG grounding · Audit logging · Human-in-the-loop approval
        </p>
      </div>

      {/* Tab strip */}
      <AgentTabs campaigns={campaigns} />
    </div>
  );
}

// Server component shells — tab switching is handled client-side via the wrapper
function AgentTabs({ campaigns }: { campaigns: Awaited<ReturnType<typeof api.campaigns.list>> }) {
  return <AgentTabsClient campaigns={campaigns} />;
}

// We need a thin client wrapper for the tab toggle
import AgentTabsClient from "@/components/agent/AgentTabsClient";
