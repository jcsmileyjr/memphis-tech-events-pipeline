"use client";

import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { HourCount } from "@/lib/api";
import { hourLabel } from "@/lib/format";
import { AXIS_TEXT, BAR_COLOR, CHART_HEIGHT, FALLBACK_SIZE, GRID_LINE } from "./chartTheme";

export default function HourChart({ data }: { data: HourCount[] }) {
  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT} initialDimension={FALLBACK_SIZE}>
      <BarChart data={data} margin={{ top: 20, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid vertical={false} stroke={GRID_LINE} />
        <XAxis
          dataKey="hour"
          tickFormatter={hourLabel}
          angle={-45}
          textAnchor="end"
          height={50}
          interval={0}
          tick={{ fill: AXIS_TEXT, fontSize: 12 }}
        />
        <YAxis allowDecimals={false} tick={{ fill: AXIS_TEXT, fontSize: 12 }} width={36} />
        <Tooltip
          labelFormatter={(hour) => `Starts in the ${hourLabel(Number(hour))} hour`}
          formatter={(value) => [value, "Events"]}
        />
        <Bar dataKey="event_count" name="Events" fill={BAR_COLOR} isAnimationActive={false}>
          <LabelList dataKey="event_count" position="top" fill={AXIS_TEXT} fontSize={11} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
