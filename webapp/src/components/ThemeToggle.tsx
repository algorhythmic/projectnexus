import { useState, useEffect } from "react"
import { Sun, Moon } from "lucide-react"
import { Button } from "./ui/button"

export function ThemeToggle() {
  const [isDark, setIsDark] = useState(false)

  useEffect(() => {
    const theme = localStorage.getItem("theme")
    const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches

    if (theme === "dark" || (!theme && systemPrefersDark)) {
      setIsDark(true)
      document.documentElement.classList.add("dark")
    } else {
      setIsDark(false)
      document.documentElement.classList.remove("dark")
    }
  }, [])

  const toggleTheme = () => {
    const newTheme = !isDark
    setIsDark(newTheme)

    if (newTheme) {
      document.documentElement.classList.add("dark")
      localStorage.setItem("theme", "dark")
    } else {
      document.documentElement.classList.remove("dark")
      localStorage.setItem("theme", "light")
    }
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      className="h-8 w-8 border-2 border-black bg-white hover:bg-yellow-300 dark:bg-gray-800 dark:border-black dark:hover:bg-gray-700"
    >
      {isDark ? (
        <Sun className="h-4 w-4 text-black dark:text-white" />
      ) : (
        <Moon className="h-4 w-4 text-black dark:text-white" />
      )}
      <span className="sr-only">Toggle theme</span>
    </Button>
  )
}
