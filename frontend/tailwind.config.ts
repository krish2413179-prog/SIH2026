import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // VASP node color coding (Requirement 10.1)
        'node-vasp': '#3B82F6',       // blue — known VASP
        'node-unknown': '#9CA3AF',    // gray — unknown
        'node-flagged': '#EF4444',    // red — flagged / high-risk
        'node-mixer': '#8B5CF6',      // purple — mixer / obfuscation
        'node-bridge': '#F59E0B',     // amber — bridge contract

        // Risk bands (Requirement 8.3)
        'risk-low': '#22C55E',        // green
        'risk-medium': '#F59E0B',     // amber
        'risk-high': '#EF4444',       // red
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      keyframes: {
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-slow': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
      },
      animation: {
        'fade-in-up': 'fade-in-up 0.8s ease-out forwards',
        'pulse-slow': 'pulse-slow 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};

export default config;
