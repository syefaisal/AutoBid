import { cn } from "@/lib/utils";

interface Props {
  label: string;
  value: string | number;
  sub?: string;
  trend?: number;
  highlight?: "green" | "red" | "yellow" | "blue" | "none";
  className?: string;
}

export function StatCard({ label, value, sub, trend, highlight = "none", className }: Props) {
  const hlClass = {
    green: "border-green-500/30 bg-green-500/5",
    red: "border-red-500/30 bg-red-500/5",
    yellow: "border-yellow-500/30 bg-yellow-500/5",
    blue: "border-violet-500/30 bg-violet-500/5",
    none: "border-gray-800 bg-[#111827]",
  }[highlight];

  return (
    <div className={cn("rounded-xl border p-4", hlClass, className)}>
      <p className="text-xs text-gray-500 uppercase tracking-wider font-medium">{label}</p>
      <p className="text-2xl font-bold mt-1 text-white">{value}</p>
      {sub && (
        <p className={cn("text-xs mt-0.5", trend != null && trend > 0 ? "text-green-400" : trend != null && trend < 0 ? "text-red-400" : "text-gray-500")}>
          {trend != null && trend > 0 ? "▲" : trend != null && trend < 0 ? "▼" : ""} {sub}
        </p>
      )}
    </div>
  );
}
