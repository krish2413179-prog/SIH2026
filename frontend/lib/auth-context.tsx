"use client"

/**
 * Auth context — HACKATHON MODE
 * Auto-logs in as demo investigator on first load.
 * No login screen needed. Judges open the app and go straight to the dashboard.
 */
import * as React from "react"
import { authApi, tokenStorage } from "@/lib/api"

// Demo credentials — pre-seeded in the DB
const DEMO_EMAIL = "investigator@lea.gov.in"
const DEMO_PASSWORD = "demo1234"

interface AuthUser {
  email: string
  name: string
}

interface AuthContextValue {
  user: AuthUser | null
  isLoading: boolean
  logout: () => void
}

const AuthContext = React.createContext<AuthContextValue | null>(null)

function decodeUser(token: string): AuthUser | null {
  try {
    const payload = JSON.parse(
      atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))
    )
    return {
      email: payload.sub || DEMO_EMAIL,
      name: payload.name || "Investigator",
    }
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = React.useState(true)

  React.useEffect(() => {
    async function init() {
      // Check for existing valid token first
      const existing = tokenStorage.getAccess()
      if (existing) {
        const decoded = decodeUser(existing)
        if (decoded) {
          setUser(decoded)
          setIsLoading(false)
          return
        }
      }

      // Auto-login with demo credentials
      try {
        const { data } = await authApi.login(DEMO_EMAIL, DEMO_PASSWORD)
        tokenStorage.set(data.access_token, data.refresh_token)
        const decoded = decodeUser(data.access_token)
        setUser(decoded ?? { email: DEMO_EMAIL, name: "Investigator" })
      } catch (err) {
        console.error("Auto-login failed:", err)
        // Still allow the app to load — API calls may fail gracefully
        setUser({ email: DEMO_EMAIL, name: "Investigator" })
      } finally {
        setIsLoading(false)
      }
    }
    init()
  }, [])

  const logout = () => {
    tokenStorage.clear()
    setUser(null)
    // Re-init auto-login on next render
    window.location.reload()
  }

  return (
    <AuthContext.Provider value={{ user, isLoading, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = React.useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider")
  return ctx
}
