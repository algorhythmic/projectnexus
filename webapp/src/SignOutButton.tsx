"use client";
import { useAuthActions } from "@convex-dev/auth/react";
import { useConvexAuth } from "convex/react";

export function SignOutButton() {
  const { isAuthenticated } = useConvexAuth();
  const { signOut } = useAuthActions();

  if (!isAuthenticated) {
    return null;
  }

  return (
    <button
      className="px-3 py-2 bg-white text-black font-semibold border-2 border-black rounded-md shadow-[4px_4px_0px_0px_#000] hover:shadow-[2px_2px_0px_0px_#000] hover:translate-x-[2px] hover:translate-y-[2px] active:shadow-none active:translate-x-[4px] active:translate-y-[4px] transition-all focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:bg-gray-700 dark:text-white dark:border-black dark:shadow-[4px_4px_0px_0px_#000] dark:hover:shadow-[2px_2px_0px_0px_#000] dark:focus:ring-blue-400"
      onClick={() => void signOut()}
    >
      Sign out
    </button>
  );
}
