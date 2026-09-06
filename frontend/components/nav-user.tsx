"use client"

import {
  IconDotsVertical,
  IconLogout,
  IconSettings,
  IconUserCircle,
} from "@tabler/icons-react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
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

function initials(name: string): string {
  return name
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("")
}

export function NavUser() {
  const { user, logout } = useAuth()

  const displayName = user?.name ?? "Investigator"
  const displayEmail = user?.email ?? ""
  const abbr = initials(displayName || displayEmail)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 h-auto hover:bg-accent"
        >
          <Avatar className="h-8 w-8 rounded-lg">
            <AvatarFallback className="rounded-lg text-xs">
              {abbr}
            </AvatarFallback>
          </Avatar>
          <div className="grid flex-1 text-left text-sm leading-tight">
            <span className="truncate font-semibold">{displayName}</span>
            <span className="truncate text-xs text-muted-foreground">
              {displayEmail}
            </span>
          </div>
          <IconDotsVertical className="ml-auto size-4 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        className="w-56 rounded-lg"
        side="top"
        align="end"
        sideOffset={4}
      >
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col gap-0.5">
            <span className="font-medium text-sm">{displayName}</span>
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
  )
}
