"use client"

import * as React from "react"
import { Area, AreaChart, CartesianGrid, XAxis } from "recharts"
import { useIsMobile } from "@/hooks/use-mobile"
import {
  Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig,
} from "@/components/ui/chart"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useCases } from "@/lib/hooks"
import api from "@/lib/api"
import { useQuery } from "@tanstack/react-query"

export const description = "Trace activity over time"

const chartConfig = {
  traces: { label: "Traces", color: "var(--primary)" },
  high_risk: { label: "High Risk", color: "var(--primary)" },
} satisfies ChartConfig

/** Aggregate trace jobs by day from /cases + wallets data */
function useTraceActivityData(days: number) {
  return useQuery({
    queryKey: ["trace-activity", days],
    queryFn: async () => {
      // Get all cases and their trace jobs, build daily aggregates
      const casesResp = await api.get<any>("/cases", { params: { page_size: 100 } })
      const cases = casesResp.data.items ?? []

      // Collect all trace jobs across all cases
      const traceArrays = await Promise.all(
        cases.slice(0, 10).map((c: any) =>
          api.get<any[]>(`/cases/${c.id}/wallets`).then(r => r.data).catch(() => [])
        )
      )
      const allTraces = traceArrays.flat()

      // Build daily buckets
      const now = new Date()
      const buckets: Record<string, { date: string; traces: number; high_risk: number }> = {}
      for (let i = days - 1; i >= 0; i--) {
        const d = new Date(now)
        d.setDate(d.getDate() - i)
        const key = d.toISOString().split("T")[0]
        buckets[key] = { date: key, traces: 0, high_risk: 0 }
      }

      for (const trace of allTraces) {
        const ts = trace.enqueued_at || trace.completed_at
        if (!ts) continue
        const key = ts.split("T")[0]
        if (buckets[key]) {
          buckets[key].traces += 1
          if ((trace.risk_score ?? 0) >= 70) buckets[key].high_risk += 1
        }
      }

      return Object.values(buckets)
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
  })
}

export function ChartAreaInteractive() {
  const isMobile = useIsMobile()
  const [timeRange, setTimeRange] = React.useState("90d")

  React.useEffect(() => {
    if (isMobile) setTimeRange("7d")
  }, [isMobile])

  const days = timeRange === "7d" ? 7 : timeRange === "30d" ? 30 : 90
  const { data: activityData, isLoading } = useTraceActivityData(days)

  const chartData = activityData ?? []
  const totalTraces = chartData.reduce((s, d) => s + d.traces, 0)

  return (
    <Card className="@container/card">
      <CardHeader>
        <CardTitle>Trace Activity</CardTitle>
        <CardDescription>
          <span className="hidden @[540px]/card:block">
            {totalTraces} trace{totalTraces !== 1 ? "s" : ""} in the last {days} days
          </span>
          <span className="@[540px]/card:hidden">{days}d activity</span>
        </CardDescription>
        <CardAction>
          <ToggleGroup
            type="single"
            value={timeRange}
            onValueChange={setTimeRange}
            variant="outline"
            className="hidden *:data-[slot=toggle-group-item]:px-4! @[767px]/card:flex"
          >
            <ToggleGroupItem value="90d">Last 3 months</ToggleGroupItem>
            <ToggleGroupItem value="30d">Last 30 days</ToggleGroupItem>
            <ToggleGroupItem value="7d">Last 7 days</ToggleGroupItem>
          </ToggleGroup>
          <Select value={timeRange} onValueChange={setTimeRange}>
            <SelectTrigger
              className="flex w-40 **:data-[slot=select-value]:block **:data-[slot=select-value]:truncate @[767px]/card:hidden"
              size="sm"
              aria-label="Select time range"
            >
              <SelectValue placeholder="Last 3 months" />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              <SelectItem value="90d" className="rounded-lg">Last 3 months</SelectItem>
              <SelectItem value="30d" className="rounded-lg">Last 30 days</SelectItem>
              <SelectItem value="7d" className="rounded-lg">Last 7 days</SelectItem>
            </SelectContent>
          </Select>
        </CardAction>
      </CardHeader>
      <CardContent className="px-2 pt-4 sm:px-6 sm:pt-6">
        {isLoading ? (
          <div className="aspect-auto h-[250px] w-full animate-pulse rounded bg-muted" />
        ) : (
          <ChartContainer config={chartConfig} className="aspect-auto h-[250px] w-full">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="fillTraces" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-traces)" stopOpacity={1.0} />
                  <stop offset="95%" stopColor="var(--color-traces)" stopOpacity={0.1} />
                </linearGradient>
                <linearGradient id="fillHighRisk" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--color-high_risk)" stopOpacity={0.8} />
                  <stop offset="95%" stopColor="var(--color-high_risk)" stopOpacity={0.1} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} />
              <XAxis
                dataKey="date"
                tickLine={false}
                axisLine={false}
                tickMargin={8}
                minTickGap={32}
                tickFormatter={(value) =>
                  new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                }
              />
              <ChartTooltip
                cursor={false}
                content={
                  <ChartTooltipContent
                    labelFormatter={(value) =>
                      new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" })
                    }
                    indicator="dot"
                  />
                }
              />
              <Area
                dataKey="high_risk"
                type="natural"
                fill="url(#fillHighRisk)"
                stroke="var(--color-high_risk)"
                stackId="a"
              />
              <Area
                dataKey="traces"
                type="natural"
                fill="url(#fillTraces)"
                stroke="var(--color-traces)"
                stackId="a"
              />
            </AreaChart>
          </ChartContainer>
        )}
      </CardContent>
    </Card>
  )
}
