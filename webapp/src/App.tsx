import { Authenticated, Unauthenticated } from "convex/react";
import { SignInForm } from "./SignInForm";
import { Toaster } from "sonner";
import { Dashboard } from "./components/Dashboard";
import { GraphPaperBackground } from "./components/GraphPaperBackground";

export default function App() {
  return (
    <GraphPaperBackground>
      <Authenticated>
        <div className="min-h-screen bg-black">
          <Dashboard />
        </div>
      </Authenticated>

      <Unauthenticated>
        <div className="min-h-screen flex items-center justify-center">
          <div className="relative max-w-md w-full space-y-8 p-8 bg-black/80 border-2 border-[#4CAF50] rounded-lg shadow-neo-glow-border transition-all duration-300 font-sans group hover:shadow-neo-glow-dark">
            {/* Border glow effect */}
            <div className="absolute -inset-0.5 rounded-lg bg-gradient-to-r from-[#4CAF50] to-[#8BC34A] opacity-0 group-hover:opacity-30 transition-opacity duration-300 -z-10"></div>
            <div className="absolute -top-8 right-0 w-[20%] animate-pulse z-50" 
            style={{ animationDuration: '4s' }}
            >
              <img
                src="/under-construction-icon-comp.webp"
                alt="Under Construction"
                className="w-full"
                style={{ transform: 'rotate(20deg)' }}
              />
            </div>
            <div className="text-center">
              <h1 className="text-5xl font-bold mb-3 tracking-tight bg-gradient-to-r from-[#29903B] via-[#4CAF50] to-[#8BC34A] bg-clip-text text-transparent">
                Market Finder
              </h1>
              <p className="text-lg text-gray-300 mb-8">
                Discover arbitrage opportunities
              </p>
            </div>
            <SignInForm />
          </div>
        </div>
      </Unauthenticated>

      <Toaster position="top-center" theme="dark" />
    </GraphPaperBackground>
  );
}
