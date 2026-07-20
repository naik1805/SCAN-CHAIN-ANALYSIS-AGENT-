import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        bg: "#090B12",
        card: "#111827",
        border: "#2D3748",
        primary: "#7C3AED",
        danger: "#EF4444",
        success: "#10B981",
        warning: "#F59E0B",
      },
      borderRadius: {
        glass: "20px",
      },
      fontFamily: {
        display: ["var(--font-display)", "Segoe UI", "sans-serif"],
        body: ["var(--font-body)", "Segoe UI", "sans-serif"],
      },
      boxShadow: {
        glass: "0 8px 32px rgba(0,0,0,0.35)",
        lift: "0 12px 40px rgba(124, 58, 237, 0.18)",
      },
    },
  },
  plugins: [],
};

export default config;
