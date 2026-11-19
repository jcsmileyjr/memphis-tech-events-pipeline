"use client";

import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MonthCount } from "@/lib/api";
import { AXIS_TEXT, BAR_COLOR, CHART_HEIGHT, FALLBACK_SIZE, GRID_LINE } from "./chartTheme";

export default function MonthlyChart({ data }: { data: MonthCount[] }) {
  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT} initialDimension={FALLBACK_SIZE}>
      <BarChart data={data} margin={{ top: 20, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid vertical={false} stroke={GRID_LINE} />
        <XAxis
          dataKey="month"
          angle={-45}
          textAnchor="end"
          height={60}
          interval={0}
          tick={{ fill: AXIS_TEXT, fontSize: 12 }}
        />
        <YAxis allowDecimals={false} tick={{ fill: AXIS_TEXT, fontSize: 12 }} width={36} />
        <Tooltip formatter={(value) => [value, "Events"]} />
        <Bar dataKey="event_count" name="Events" fill={BAR_COLOR} isAnimationActive={false}>
          <LabelList dataKey="event_count" position="top" fill={AXIS_TEXT} fontSize={11} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
