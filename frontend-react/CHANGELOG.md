# Changelog

All notable changes to the Vietnam Legal Agent frontend are documented in this file.

## [1.0.0] - 2025-04-04

### 🎉 Initial Release - Phase 1 & 2 Complete

#### ✨ Features
- **Real-time SSE Streaming** - Token-by-token response streaming with abort control
- **Session Management** - Create, load, delete, and rename conversations through the backend persistence API
- **Markdown Rendering** - Full GFM support with syntax highlighting for code blocks
- **Auto-Scroll** - Intelligent scroll behavior with scroll-to-bottom button
- **Keyboard Shortcuts** - Enter to send, Escape to stop generation
- **Dark Mode** - Full dark mode support with smooth transitions
- **Toast Notifications** - User feedback for all actions
- **Error Boundaries** - Graceful error handling with retry functionality
- **Health Monitoring** - Backend status indicator in header
- **Welcome Screen** - Beautiful onboarding with example prompts

#### 🎨 UI/UX
- Modern ChatGPT-inspired design with green primary color
- Smooth animations and transitions (cubic-bezier easing)
- Glass morphism effects and backdrop blur
- Gradient accents and shadow layers
- Skeleton loading states with shimmer effects
- Responsive sidebar with search and session management
- Beautiful message bubbles with gradient avatars
- Hover-reveal action buttons (copy, regenerate, feedback)
- Expandable source documents section
- Typing indicator with animated bouncing dots

#### 🛠️ Tech Stack
- React 18 + TypeScript
- Vite 5 (fast HMR)
- Tailwind CSS (utility-first styling)
- Zustand (lightweight state management)
- Axios + Fetch API (HTTP client)
- react-markdown + remark-gfm (markdown rendering)
- react-syntax-highlighter (code highlighting)

#### 🏗️ Architecture
- Component-based architecture with clear separation of concerns
- Zustand stores for chat and session state
- Custom hooks for streaming, sessions, auto-scroll, keyboard shortcuts
- Full TypeScript type definitions
- Error boundaries for graceful error handling
- Toast notification system

#### 📁 Project Structure
```
frontend-react/
├── src/
│   ├── api/              # API client and endpoints
│   ├── components/       # React components
│   │   ├── Chat/         # Chat-related components
│   │   ├── Layout/       # Layout components
│   │   ├── Onboarding/   # Welcome and prompts
│   │   └── UI/           # Reusable UI primitives
│   ├── hooks/            # Custom React hooks
│   ├── state/            # Zustand stores
│   ├── types/            # TypeScript type definitions
│   ├── utils/            # Utility functions
│   └── lib/              # Shared libraries
├── public/               # Static assets
├── index.html            # HTML entry point
├── package.json          # Dependencies
├── vite.config.ts        # Vite configuration
├── tsconfig.json         # TypeScript configuration
└── tailwind.config.js    # Tailwind CSS configuration
```

#### 🔧 Configuration
- `VITE_API_BASE_URL` - Backend API URL (default: proxy to localhost:8000)
- `VITE_OIDC_ISSUER`, `VITE_OIDC_CLIENT_ID`, and `VITE_OIDC_REDIRECT_URI` - browser OIDC login configuration

#### 🚀 Scripts
```bash
npm run dev       # Start development server
npm run build     # Build for production
npm run preview   # Preview production build
npm run lint      # Run ESLint
npm run format    # Format code with Prettier
```

#### 🐛 Bug Fixes
- Fixed duplicate `cn` utility (removed `utils.ts`)
- Fixed `setStreaming` type safety (removed `as any` cast)
- Fixed misplaced import in `api.ts`
- Fixed package versions (vite 5.x, plugin-react 4.x)

#### ✅ Testing
- Vitest coverage for frontend utilities, state, rendering, and API contracts
- Playwright coverage for the deterministic browser journeys
- SSE streaming, session persistence, feedback, and safe-stop flows exercised by the test suite

### 📋 Current boundary

This entry records the initial frontend implementation. Current behavior and
supported capabilities are defined by the React source, the browser contract,
and the validation commands in the repository README; it is not a roadmap.
