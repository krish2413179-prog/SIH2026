'use client';

/**
 * Client-side RBAC guard.
 *
 * Usage:
 *   <RoleGuard requiredRole="supervisor">
 *     <AdminPanel />
 *   </RoleGuard>
 *
 * Role hierarchy (ascending privilege):
 *   investigator < supervisor < admin
 *
 * If the current user's role does not meet the minimum required role the
 * component redirects to /dashboard (or a custom `fallbackPath`).
 *
 * Requirements: 1.1, 16.2
 */

import { useEffect, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { getCurrentUser, isAuthenticated, type UserInfo } from './auth';

// ---------------------------------------------------------------------------
// Role hierarchy
// ---------------------------------------------------------------------------

const ROLE_RANK: Record<UserInfo['role'], number> = {
  investigator: 1,
  supervisor: 2,
  admin: 3,
};

function hasRequiredRole(
  userRole: UserInfo['role'],
  requiredRole: UserInfo['role']
): boolean {
  return (ROLE_RANK[userRole] ?? 0) >= (ROLE_RANK[requiredRole] ?? 0);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface RoleGuardProps {
  /** Minimum role required to render children. */
  requiredRole: UserInfo['role'];
  /** Path to redirect to when the role check fails. Defaults to /dashboard. */
  fallbackPath?: string;
  /**
   * Optional element to render while the role check is running (first render
   * only, before the redirect fires). Defaults to null.
   */
  fallback?: ReactNode;
  children: ReactNode;
}

export function RoleGuard({
  requiredRole,
  fallbackPath = '/dashboard',
  fallback = null,
  children,
}: RoleGuardProps) {
  const router = useRouter();

  const authenticated = isAuthenticated();
  const user = getCurrentUser();

  useEffect(() => {
    if (!authenticated) {
      router.replace('/auth/login');
      return;
    }

    if (!user || !hasRequiredRole(user.role, requiredRole)) {
      router.replace(fallbackPath);
    }
  }, [authenticated, user, requiredRole, fallbackPath, router]);

  // While the redirect is being evaluated on the first render, show the
  // fallback so no flash of protected content occurs.
  if (!authenticated || !user || !hasRequiredRole(user.role, requiredRole)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}

// ---------------------------------------------------------------------------
// HOC variant (optional convenience)
// ---------------------------------------------------------------------------

/**
 * Higher-order component variant.
 *
 * Usage:
 *   export default withRoleGuard(MyPage, 'admin');
 */
export function withRoleGuard<P extends object>(
  Component: React.ComponentType<P>,
  requiredRole: UserInfo['role'],
  options?: { fallbackPath?: string; fallback?: ReactNode }
) {
  function GuardedComponent(props: P) {
    return (
      <RoleGuard
        requiredRole={requiredRole}
        fallbackPath={options?.fallbackPath}
        fallback={options?.fallback}
      >
        <Component {...props} />
      </RoleGuard>
    );
  }
  GuardedComponent.displayName = `withRoleGuard(${Component.displayName ?? Component.name})`;
  return GuardedComponent;
}
