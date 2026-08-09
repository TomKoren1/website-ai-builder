"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export function Header() {
  const { user, logout } = useAuth();
  if (!user) return null;

  return (
    <header className="border-b px-6 py-3 flex items-center justify-between">
      <Link href="/dashboard" className="font-semibold">
        AI Website Builder
      </Link>
      <nav className="flex items-center gap-4 text-sm">
        <Link href="/dashboard" className="hover:underline">
          Projects
        </Link>
        <Link href="/api-keys" className="hover:underline">
          API Keys
        </Link>
        <span className="text-gray-500">{user.email}</span>
        <button onClick={() => logout()} className="underline">
          Log out
        </button>
      </nav>
    </header>
  );
}
