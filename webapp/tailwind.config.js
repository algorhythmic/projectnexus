/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        input: {
          DEFAULT: '#D1D5DB', // gray-300
          dark: '#000000',
        },
        primary: {
          DEFAULT: "#3b82f6",
          hover: "#2563eb",
        },
        secondary: {
          DEFAULT: "#6b7280",
          hover: "#4b5563",
        },
        main: { DEFAULT: '#ffffff', dark: '#1F2937' },
        'main-foreground': { DEFAULT: '#000000', dark: '#f9fafb' },
        border: '#e5e7eb',
        'secondary-background': { DEFAULT: '#f3f4f6', dark: '#374151' },
      },
      borderRadius: {
        container: "0.75rem",
        base: "0.5rem",
      },
      boxShadow: {
        'neo-glow-dark': '0 0 50px rgba(41, 237, 94, 0.8)',
        'neo-glow-border': '0 0 0 1px rgba(41, 237, 94, 0.8), 0 0 25px 2px rgba(41, 237, 94, 0.6)',
        shadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
        'shadow-shadow': '0 1px 2px rgba(0, 0, 0, 0.05)',
      },
      fontFamily: {
        heading: ['Inter', 'sans-serif'],
        base: ['Inter', 'sans-serif'],
      },
      backgroundImage: {
        'market-gradient': 'linear-gradient(90deg, #29903B 0%, #4CAF50 50%, #8BC34A 100%)',
        'button-gradient': 'linear-gradient(90deg, #29903B 0%, #4CAF50 100%)',
        'button-hover': 'linear-gradient(90deg, #1e7a2e 0%, #3d8b40 100%)',
      },
    },
  },
  plugins: [],
};
