"use client"

/**
 * SiteHeader — kept as a lightweight page-level sub-header.
 * The main navigation is now handled by AppBar.
 */
import {
  IconAlertTriangle,
} from "@tabler/icons-react"
import { Badge } from "@/components/ui/badge"
import { useAuth } from "@/lib/auth-context"
import { useDashboardSummary } from "@/lib/hooks"

export function SiteHeader() {
  const { user } = useAuth()
  const { data: summary } = useDashboardSummary()

  return (
    <div className="flex h-10 shrink-0 items-center gap-2 border-b px-4 lg:px-6">
      <div className="flex flex-1 items-center gap-2">
        <span className="text-sm font-medium text-muted-foreground">
          Dashboard
        </span>
        {user && (
          <span className="text-xs text-muted-foreground/60 hidden sm:inline">
            · {user.name}
          </span>
        )}
      </div>

      {summary && (
        <div className="hidden lg:flex items-center gap-2">
          <Badge variant="outline" className="gap-1 text-xs font-normal">
            <span className="size-1.5 rounded-full bg-green-500 inline-block" />
            {summary.open_cases} open cases
          </Badge>
          {summary.active_traces > 0 && (
            <Badge variant="outline" className="gap-1 text-xs font-normal">
              <span className="size-1.5 rounded-full bg-blue-500 inline-block animate-pulse" />
              {summary.active_traces} tracing
            </Badge>
          )}
          {summary.high_risk_cases > 0 && (
            <Badge variant="destructive" className="gap-1 text-xs font-normal">
              <IconAlertTriangle className="size-3" />
              {summary.high_risk_cases} high risk
            </Badge>
          )}
        </div>
      )}
    </div>
  )
}
