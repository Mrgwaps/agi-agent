/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './src/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        background: '#0a0a0f',
        card: '#111118',
        border: '#1e1e2e',
        primary: {
          DEFAULT: '#6366f1',
          hover: '#4f46e5',
          light: '#818cf8',
        },
        success: '#22c55e',
        warning: '#f59e0b',
        error: '#ef4444',
        text: {
          DEFAULT: '#e2e8f0',
          muted: '#64748b',
        },
        accent: '#818cf8',
        surface: {
          DEFAULT: '#111118',
          elevated: '#16161f',
          overlay: '#1a1a26',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-glow': 'pulse-glow 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-in': 'slide-in 0.3s ease-out',
        'spin-slow': 'spin 2s linear infinite',
        'fade-in': 'fade-in 0.2s ease-out',
        'shimmer': 'shimmer 1.5s infinite',
      },
      keyframes: {
        'pulse-glow': {
          '0%, 100%': {
            boxShadow: '0 0 0 0 rgba(99, 102, 241, 0)',
          },
          '50%': {
            boxShadow: '0 0 20px 4px rgba(99, 102, 241, 0.3)',
          },
        },
        'slide-in': {
          from: {
            opacity: '0',
            transform: 'translateY(-8px)',
          },
          to: {
            opacity: '1',
            transform: 'translateY(0)',
          },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'shimmer': {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic': 'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
        'neural-grid': 'radial-gradient(circle, #1e1e2e 1px, transparent 1px)',
      },
      backgroundSize: {
        'grid-sm': '20px 20px',
        'grid-md': '32px 32px',
      },
      boxShadow: {
        'glow-sm': '0 0 10px rgba(99, 102, 241, 0.2)',
        'glow-md': '0 0 20px rgba(99, 102, 241, 0.3)',
        'glow-lg': '0 0 40px rgba(99, 102, 241, 0.4)',
        'card': '0 4px 24px rgba(0, 0, 0, 0.4)',
        'inner-glow': 'inset 0 1px 0 rgba(255, 255, 255, 0.05)',
      },
      borderRadius: {
        'xl': '0.75rem',
        '2xl': '1rem',
      },
    },
  },
  plugins: [],
};
