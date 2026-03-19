"use client";
import { useAuthActions } from "@convex-dev/auth/react";
import { useState } from "react";
import { toast } from "sonner";

export function SignInForm() {
  const { signIn } = useAuthActions();
  const [flow, setFlow] = useState<"signIn" | "signUp">("signIn");
  const [submitting, setSubmitting] = useState(false);

  return (
    <div className="w-full">
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitting(true);
          const formData = new FormData(e.target as HTMLFormElement);
          formData.set("flow", flow);
          void signIn("password", formData).catch((error) => {
            let toastTitle = "";
            if (error.message.includes("Invalid password")) {
              toastTitle = "Invalid password. Please try again.";
            } else {
              toastTitle =
                flow === "signIn"
                  ? "Could not sign in, did you mean to sign up?"
                  : "Could not sign up, did you mean to sign in?";
            }
            toast.error(toastTitle);
            setSubmitting(false);
          });
        }}
      >
        <input
          className="w-full px-4 py-3 bg-black/40 border-2 border-[#29903B]/50 text-white placeholder-gray-400 font-sans focus:outline-none focus:border-[#4CAF50] focus:ring-1 focus:ring-[#4CAF50] rounded transition-all duration-200"
          type="email"
          name="email"
          placeholder="EMAIL"
          required
        />
        <input
          className="w-full px-4 py-3 bg-black/40 border-2 border-[#29903B]/50 text-white placeholder-gray-400 font-sans focus:outline-none focus:border-[#4CAF50] focus:ring-1 focus:ring-[#4CAF50] rounded transition-all duration-200"
          type="password"
          name="password"
          placeholder="PASSWORD"
          required
        />
        <button 
          className="w-full px-4 py-3 bg-gradient-to-r from-[#29903B] to-[#4CAF50] text-white font-sans font-bold border-2 border-transparent hover:from-[#1e7a2e] hover:to-[#3d8b40] transition-all duration-300 flex items-center justify-center gap-2 rounded-md shadow-lg hover:shadow-[0_0_15px_rgba(41,144,59,0.5)]"
          type="submit" 
          disabled={submitting}
        >
          {submitting ? (
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
          ) : null}
          {flow === "signIn" ? "SIGN IN" : "SIGN UP"}
        </button>
        <div className="text-center text-sm text-gray-300 font-sans">
          <span>
            {flow === "signIn"
              ? "NO ACCOUNT? "
              : "ALREADY HAVE AN ACCOUNT? "}
          </span>
          <button
            type="button"
            className="text-[#29903B] hover:underline font-bold cursor-pointer"
            onClick={() => setFlow(flow === "signIn" ? "signUp" : "signIn")}
          >
            {flow === "signIn" ? "SIGN UP" : "SIGN IN"}
          </button>
        </div>
      </form>
      <div className="flex items-center justify-center my-6">
        <hr className="grow border-[#29903B]/30 drop-shadow-[0_0_3px_rgba(41,144,59,0.5)]" />
        <span className="mx-4 text-gray-400 font-sans text-sm">OR</span>
        <hr className="grow border-[#29903B]/30 drop-shadow-[0_0_3px_rgba(41,144,59,0.5)]" />
      </div>
      <button 
        className="w-full px-4 py-3 bg-transparent text-white font-sans font-bold border-2 border-[#4CAF50] hover:bg-[#1e7a2e]/20 hover:border-[#4CAF50] transition-all duration-300 rounded-md hover:shadow-[0_0_15px_rgba(41,144,59,0.3)]" 
        onClick={() => void signIn("anonymous")}
      >
        CONTINUE AS GUEST
      </button>
    </div>
  );
}
