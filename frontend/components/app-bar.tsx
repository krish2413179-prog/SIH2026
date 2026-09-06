"use client"

import * as React from "react"
import {
  IconAlertTriangle,
  IconChartBar,
  IconDatabase,
  IconFileDescription,
  IconLogout,
  IconNetwork,
  IconSearch,
  IconSettings,
  IconShield,
  IconUserCircle,
} from "@tabler/icons-react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useAuth } from "@/lib/auth-context"
import { useDashboardSummary } from "@/lib/hooks"

function initials(name: string): string {
  return name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("")
}

const NAV_ITEMS = [
  { label: "Investigations", icon: IconNetwork, href: "#" },
  { label: "Analytics", icon: IconChartBar, href: "#" },
  { label: "VASP Registry", icon: IconDatabase, href: "#" },
  { label: "Reports", icon: IconFileDescription, href: "#" },
]

export function AppBar() {
  const { user, logout } = useAuth()
  const { data: summary } = useDashboardSummary()

  const displayName = user?.name ?? "Investigator"
  const displayEmail = user?.email ?? ""
  const abbr = initials(displayName || displayEmail)

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border/60 bg-background/95 backdrop-blur-sm supports-[backdrop-filter]:bg-background/80">
      <div className="flex h-14 items-center gap-4 px-4 lg:px-6">

        {/* ── Brand ─────────────────────────────────────── */}
        <a href="#" className="flex items-center gap-2.5 shrink-0 group">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm group-hover:bg-primary/90 transition-colors">
            <IconShield className="size-4" />
          </div>
          <div className="hidden sm:flex flex-col leading-none">
            <span className="text-sm font-bold tracking-tight">VASP Intelligence</span>
            <span className="text-[10px] text-muted-foreground font-medium tracking-widest uppercase">
              Blockchain · LEA
            </span>
          </div>
        </a>

        <div className="h-5 w-px bg-border hidden sm:block shrink-0" />

        {/* ── Nav links ─────────────────────────────────── */}
        <nav className="hidden md:flex items-center gap-1">
          {NAV_ITEMS.map(({ label, icon: Icon, href }) => (
            <a
              key={label}
              href={href}
              className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
            >
              <Icon className="size-3.5" />
              {label}
            </a>
          ))}
        </nav>

        {/* ── Spacer ────────────────────────────────────── */}
        <div className="flex-1" />

        {/* ── Live stats ────────────────────────────────── */}
        {summary && (
          <div className="hidden lg:flex items-center gap-2">
            <Badge
              variant="outline"
              className="gap-1.5 text-xs font-normal border-green-500/40 text-green-600 dark:text-green-400"
            >
              <span className="size-1.5 rounded-full bg-green-500 inline-block" />
              {summary.open_cases} open
            </Badge>
            {summary.active_traces > 0 && (
              <Badge
                variant="outline"
                className="gap-1.5 text-xs font-normal border-blue-500/40 text-blue-600 dark:text-blue-400"
              >
                <span className="size-1.5 rounded-full bg-blue-500 inline-block animate-pulse" />
                {summary.active_traces} tracing
              </Badge>
            )}
            {summary.high_risk_cases > 0 && (
              <Badge
                variant="destructive"
                className="gap-1.5 text-xs font-normal"
              >
                <IconAlertTriangle className="size-3" />
                {summary.high_risk_cases} high risk
              </Badge>
            )}
          </div>
        )}

        {/* ── Search ────────────────────────────────────── */}
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-foreground"
          aria-label="Search"
        >
          <IconSearch className="size-4" />
        </Button>

        {/* ── Settings ──────────────────────────────────── */}
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-foreground hidden sm:inline-flex"
          aria-label="Settings"
        >
          <IconSettings className="size-4" />
        </Button>

        {/* ── User menu ─────────────────────────────────── */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="flex items-center gap-2 h-8 px-2 rounded-lg hover:bg-accent"
              aria-label="User menu"
            >
              <Avatar className="size-7 rounded-md">
                <AvatarFallback className="rounded-md text-[11px] font-semibold bg-primary/10 text-primary">
                  {abbr}
                </AvatarFallback>
              </Avatar>
              <div className="hidden sm:flex flex-col text-left leading-none">
                <span className="text-xs font-semibold truncate max-w-[100px]">
                  {displayName}
                </span>
                <span className="text-[10px] text-muted-foreground truncate max-w-[100px]">
                  {displayEmail}
                </span>
              </div>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-56 rounded-lg"
            align="end"
            sideOffset={8}
          >
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col gap-0.5">
                <span className="font-semibold text-sm">{displayName}</span>
                <span className="text-xs text-muted-foreground">{displayEmail}</span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem>
              <IconUserCircle className="size-4" />
              Account
            </DropdownMenuItem>
            <DropdownMenuItem>
              <IconSettings className="size-4" />
              Settings
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={logout}
              className="text-destructive focus:text-destructive"
            >
              <IconLogout className="size-4" />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
