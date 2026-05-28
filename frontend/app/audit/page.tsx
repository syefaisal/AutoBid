import { AuditLogView } from "@/components/dashboard/AuditLogView";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AuditPage() {
  let logs: Awaited<ReturnType<typeof api.audit.list>> = [];
  try {
    logs = await api.audit.list();
  } catch {}

  return (
    <div className="p-6 space-y-4 max-w-7xl">
      <div>
        <h1 className="text-2xl font-bold text-white">Audit Log</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Immutable record of all agent actions · Approval gates · Rollback support
        </p>
      </div>
      <AuditLogView initialLogs={logs} />
    </div>
  );
}
