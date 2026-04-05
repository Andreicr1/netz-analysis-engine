module.exports = {
  content: [
    "./src/**/*.{html,js,ts,jsx,tsx}",
    "app/**/*.{ts,tsx}",
    "components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        "localhostathens-gray": "var(--localhostathens-gray)",
        "localhostroyal-blue": "var(--localhostroyal-blue)",
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      fontFamily: {
        "localhost-arial-black": "var(--localhost-arial-black-font-family)",
        "localhost-arial-bold": "var(--localhost-arial-bold-font-family)",
        "localhost-arial-bold-upper":
          "var(--localhost-arial-bold-upper-font-family)",
        "localhost-arial-regular": "var(--localhost-arial-regular-font-family)",
        "localhost-arial-regular-underline":
          "var(--localhost-arial-regular-underline-font-family)",
        "localhost-cambria-math-regular":
          "var(--localhost-cambria-math-regular-font-family)",
        "localhost-cambria-math-regular-upper":
          "var(--localhost-cambria-math-regular-upper-font-family)",
        "localhost-consolas-bold": "var(--localhost-consolas-bold-font-family)",
        "localhost-consolas-regular":
          "var(--localhost-consolas-regular-font-family)",
        "localhost-geist-mono-bold":
          "var(--localhost-geist-mono-bold-font-family)",
        "localhost-geist-mono-regular":
          "var(--localhost-geist-mono-regular-font-family)",
        "localhost-geist-mono-semibold":
          "var(--localhost-geist-mono-semibold-font-family)",
        "localhost-inter-regular": "var(--localhost-inter-regular-font-family)",
        "localhost-urbanist-black":
          "var(--localhost-urbanist-black-font-family)",
        "localhost-urbanist-black-upper":
          "var(--localhost-urbanist-black-upper-font-family)",
        "localhost-urbanist-bold": "var(--localhost-urbanist-bold-font-family)",
        "localhost-urbanist-bold-upper":
          "var(--localhost-urbanist-bold-upper-font-family)",
        "localhost-urbanist-extrabold":
          "var(--localhost-urbanist-extrabold-font-family)",
        "localhost-urbanist-italic":
          "var(--localhost-urbanist-italic-font-family)",
        "localhost-urbanist-light":
          "var(--localhost-urbanist-light-font-family)",
        "localhost-urbanist-medium":
          "var(--localhost-urbanist-medium-font-family)",
        "localhost-urbanist-medium-underline":
          "var(--localhost-urbanist-medium-underline-font-family)",
        "localhost-urbanist-regular":
          "var(--localhost-urbanist-regular-font-family)",
        "localhost-urbanist-regular-upper":
          "var(--localhost-urbanist-regular-upper-font-family)",
        "localhost-urbanist-semibold":
          "var(--localhost-urbanist-semibold-font-family)",
        "localhost-urbanist-semibold-underline":
          "var(--localhost-urbanist-semibold-underline-font-family)",
        "localhost-urbanist-semibold-upper":
          "var(--localhost-urbanist-semibold-upper-font-family)",
        sans: [
          "ui-sans-serif",
          "system-ui",
          "sans-serif",
          '"Apple Color Emoji"',
          '"Segoe UI Emoji"',
          '"Segoe UI Symbol"',
          '"Noto Color Emoji"',
        ],
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
    container: { center: true, padding: "2rem", screens: { "2xl": "1400px" } },
  },
  plugins: [],
  darkMode: ["class"],
};
