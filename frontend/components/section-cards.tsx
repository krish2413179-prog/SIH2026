"use client"

import { IconAlertTriangle, IconClipboardList, IconLoader2, IconNetwork, IconSend, IconTrendingDown, IconTrendingUp } from "@tabler/icons-react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useDashboardSummary } from "@/lib/hooks"

function SkeletonCard() {
  return (
    <Card className="@container/card">
      <CardHeader>
        <CardDescription className="h-4 w-24 animate-pulse rounded bg-muted" />
        <CardTitle className="h-8 w-20 animate-pulse rounded bg-muted" />
      </CardHeader>
      <CardFooter className="flex-col items-start gap-1.5 text-sm">
        <div className="h-4 w-32 animate-pulse rounded bg-muted" />
      </CardFooter>
    </Card>
  )
}

export function SectionCards() {
  const { data, isLoading } = useDashboardSummary()

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 px-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4 dark:*:data-[slot=card]:bg-card">
        <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
      </div>
    )
  }

  const openCases = data?.open_cases ?? 0
  const activeTraces = data?.active_traces ?? 0
  const highRisk = data?.high_risk_cases ?? 0
  const pendingSahyog = data?.pending_sahyog ?? 0

  return (
    <div className="grid grid-cols-1 gap-4 px-4 *:data-[slot=card]:bg-gradient-to-t *:data-[slot=card]:from-primary/5 *:data-[slot=card]:to-card *:data-[slot=card]:shadow-xs lg:px-6 @xl/main:grid-cols-2 @5xl/main:grid-cols-4 dark:*:data-[slot=card]:bg-card">

      {/* Open Cases */}
      <Card className="@container/card">
        <CardHeader>
          <CardDescription>Open Cases</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
            {openCases.toLocaleString()}
          </CardTitle>
          <CardAction>
            <Badge variant="outline">
              <IconClipboardList className="size-3" />
              Active
            </Badge>
          </CardAction>
        </CardHeader>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            Investigation cases in progress <IconTrendingUp className="size-4" />
          </div>
          <div className="text-muted-foreground">
            Cases currently under investigation
          </div>
        </CardFooter>
      </Card>

      {/* Active Traces */}
      <Card className="@container/card">
        <CardHeader>
          <CardDescription>Active Traces</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
            {activeTraces.toLocaleString()}
          </CardTitle>
          <CardAction>
            <Badge variant="outline">
              <IconNetwork className="size-3" />
              Running
            </Badge>
          </CardAction>
        </CardHeader>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            {activeTraces > 0 ? 'Blockchain traces in progress' : 'No active traces'}{' '}
            {activeTraces > 0 ? <IconLoader2 className="size-4 animate-spin" /> : null}
          </div>
          <div className="text-muted-foreground">
            Queued or currently running
          </div>
        </CardFooter>
      </Card>

      {/* High Risk */}
      <Card className="@container/card">
        <CardHeader>
          <CardDescription>High Risk Alerts</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
            {highRisk.toLocaleString()}
          </CardTitle>
          <CardAction>
            <Badge variant={highRisk > 0 ? "destructive" : "outline"}>
              <IconAlertTriangle className="size-3" />
              {highRisk > 0 ? "Alert" : "Clear"}
            </Badge>
          </CardAction>
        </CardHeader>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            {highRisk > 0 ? 'Wallets flagged high risk' : 'No high-risk alerts'}
            {highRisk > 0 ? <IconTrendingUp className="size-4" /> : <IconTrendingDown className="size-4" />}
          </div>
          <div className="text-muted-foreground">
            Risk score ≥ 70 across all traces
          </div>
        </CardFooter>
      </Card>

      {/* Pending SAHYOG */}
      <Card className="@container/card">
        <CardHeader>
          <CardDescription>Pending SAHYOG</CardDescription>
          <CardTitle className="text-2xl font-semibold tabular-nums @[250px]/card:text-3xl">
            {pendingSahyog.toLocaleString()}
          </CardTitle>
          <CardAction>
            <Badge variant="outline">
              <IconSend className="size-3" />
              Portal
            </Badge>
          </CardAction>
        </CardHeader>
        <CardFooter className="flex-col items-start gap-1.5 text-sm">
          <div className="line-clamp-1 flex gap-2 font-medium">
            Legal notices awaiting dispatch <IconSend className="size-4" />
          </div>
          <div className="text-muted-foreground">
            Awaiting SAHYOG portal submission
          </div>
        </CardFooter>
      </Card>

    </div>
  )
}
