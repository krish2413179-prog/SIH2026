"use client"

import { IconLoader2 } from "@tabler/icons-react"
import { InvestigationWorkspace } from "@/components/investigation-workspace"
import { useAuth } from "@/lib/auth-context"

export default function Page() {
  const { isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <IconLoader2 className="size-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      <main className="flex flex-1 flex-col py-6">
        <InvestigationWorkspace />
      </main>
    </div>
  )
}
