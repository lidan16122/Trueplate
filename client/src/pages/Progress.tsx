import { useEffect, useState } from "react";
import { Link } from "react-router";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Eyebrow } from "@/components/ui";
import { api } from "@/lib/api";
import { dayOfMonth } from "@/lib/format";
import type { DaySummary } from "@/types/api";

/**
 * Placeholder — no design exists for this screen yet.
 *
 * Calorie adherence is real data (the day range endpoint already returns it).
 * The weight trend is illustrative until a weigh-in flow exists to populate
 * `weight_entries` beyond the single onboarding reading.
 *
 * This is the only screen using Recharts. The designed screens draw their bars
 * with CSS — three progress fills do not need a charting runtime, and matching
 * the design's exact bar geometry is easier without one.
 */
export function Progress() {
  const [days, setDays] = useState<DaySummary[]>([]);
  const [target, setTarget] = useState<number | null>(null);

  useEffect(() => {
    void api.logs.range(14).then(setDays);
    void api.profile
      .targets()
      .then((t) => setTarget(t.target_calories))
      .catch(() => setTarget(null));
  }, []);

  const data = days.map((day) => ({
    label: dayOfMonth(day.log_date),
    calories: Math.round(day.calories),
  }));

  return (
    <div className="min-h-dvh bg-page">
      <main className="mx-auto flex w-full max-w-[900px] flex-col gap-10 px-6 py-10 md:px-8">
        <div className="flex items-baseline justify-between">
          <div className="flex flex-col gap-2">
            <Eyebrow>Progress</Eyebrow>
            <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">
              Last 14 days
            </h1>
          </div>
          <Link to="/today" className="text-caption text-muted hover:text-ink">
            Back
          </Link>
        </div>

        <section className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5">
          <h2 className="text-caption font-semibold text-ink">Calories against target</h2>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid stroke="var(--color-line-2)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ fill: "var(--color-wash)" }}
                  contentStyle={{
                    border: "1px solid var(--color-line)",
                    borderRadius: "var(--radius-card)",
                    fontSize: 13,
                  }}
                />
                {target && (
                  <ReferenceLine
                    y={target}
                    stroke="var(--color-accent)"
                    strokeDasharray="4 4"
                    label={{ value: "target", fill: "var(--color-accent)", fontSize: 11 }}
                  />
                )}
                <Bar dataKey="calories" fill="var(--color-ink)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>

        <section className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-caption font-semibold text-ink">Weight trend</h2>
            <span className="font-mono text-label text-faint">illustrative</span>
          </div>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data.map((d, i) => ({ label: d.label, weight: 74 - i * 0.12 }))}
                margin={{ top: 8, right: 8, bottom: 0, left: -16 }}
              >
                <CartesianGrid stroke="var(--color-line-2)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={["dataMin - 1", "dataMax + 1"]}
                  tick={{ fill: "var(--color-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    border: "1px solid var(--color-line)",
                    borderRadius: "var(--radius-card)",
                    fontSize: 13,
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="weight"
                  stroke="var(--color-accent)"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="text-caption leading-relaxed text-subtle">
            Real data appears once weigh-ins are recorded — the backend stores weight as a time
            series, but nothing writes to it after onboarding yet.
          </p>
        </section>
      </main>
    </div>
  );
}
