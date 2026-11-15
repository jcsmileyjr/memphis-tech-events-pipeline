"use client";

import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CategoryCount } from "@/lib/api";
import { AXIS_TEXT, BAR_COLOR, CHART_HEIGHT, FALLBACK_SIZE, GRID_LINE } from "./chartTheme";

export default function CategoryChart({ data }: { data: CategoryCount[] }) {
  return (
    <ResponsiveContainer width="100%" height={CHART_HEIGHT} initialDimension={FALLBACK_SIZE}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 0 }}>
        <CartesianGrid horizontal={false} stroke={GRID_LINE} />
        <XAxis type="number" allowDecimals={false} tick={{ fill: AXIS_TEXT, fontSize: 12 }} />
        <YAxis
          type="category"
          dataKey="event_category"
          width={100}
          interval={0}
          tick={{ fill: AXIS_TEXT, fontSize: 13 }}
        />
        <Tooltip formatter={(value) => [value, "Events"]} />
        <Bar dataKey="event_count" name="Events" fill={BAR_COLOR} isAnimationActive={false}>
          <LabelList dataKey="event_count" position="right" fill={AXIS_TEXT} fontSize={12} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
