/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{tsx,ts}'],
  theme: {
    extend: {
      colors: {
        base: {
          50: '#e8ecf2',
          100: '#c5cdd8',
          200: '#9ca8bc',
          300: '#6e7f9a',
          400: '#4a5d7c',
          500: '#2d3f5e',
          600: '#1a2d4d',
          700: '#0f1f3a',
          800: '#0a1528',
          900: '#0a0f1a',
          950: '#060912',
        },
        amber: {
          DEFAULT: '#d4a843',
          light: '#f0c866',
          dark: '#b08828',
        },
        cyan: {
          DEFAULT: '#00d4aa',
          light: '#33e8c4',
          dark: '#00a888',
        },
        danger: {
          DEFAULT: '#ff3b3b',
          light: '#ff6666',
          dark: '#cc2e2e',
        },
        slate: {
          DEFAULT: '#8a96a8',
          light: '#a8b4c4',
          dark: '#5c6a7c',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
      },
      animation: {
        'glow-pulse': 'glow-pulse 2s ease-in-out infinite',
        'fade-in': 'fade-in 0.3s ease-out',
      },
      keyframes: {
        'glow-pulse': {
          '0%, 100%': { opacity: '0.4' },
          '50%': { opacity: '1' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
};