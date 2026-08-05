# EPR Chatbot Frontend (React)

Modern React frontend for the EPR Chatbot application, built with React 18, TypeScript, Vite, and Tailwind CSS.

## 🚀 Features

- ⚡ Fast development with Vite HMR
- 🎨 Beautiful UI with Tailwind CSS
- 📱 Responsive design (mobile-first)
- 💬 Real-time SSE streaming
- 🔄 Session management
- ✅ TypeScript for type safety
- 🎯 Zustand for lightweight state management

## 📦 Tech Stack

- **Framework:** React 18+ with TypeScript
- **Build Tool:** Vite 5
- **Styling:** Tailwind CSS
- **State Management:** Zustand
- **HTTP Client:** Axios + Fetch API (for SSE)
- **Markdown:** react-markdown + remark-gfm (planned)

## 🛠️ Setup

```bash
# Install dependencies
npm install

# Copy environment file
cp .env.example .env

# Start development server
npm run dev
```

## 📁 Project Structure

```
src/
├── api/                    # API client and endpoints
│   ├── client.ts           # Axios instance
│   ├── sessions.ts         # Session endpoints
│   └── feedback.ts         # Feedback endpoints
├── components/             # React components
│   ├── Chat/               # Chat-related components
│   └── Sidebar/            # Sidebar components
├── hooks/                  # Custom React hooks
│   ├── useChatStream.ts    # SSE streaming hook
│   └── useSessions.ts      # Session management hook
├── state/                  # Zustand stores
│   ├── chatStore.ts        # Chat state
│   └── sessionStore.ts     # Session state
├── types/                  # TypeScript type definitions
│   ├── chat.ts             # Chat types
│   └── api.ts              # API types
├── utils/                  # Utility functions
│   └── sseParser.ts        # SSE event parser
├── lib/                    # Shared libraries
│   ├── utils.ts            # General utilities
│   └── formatters.ts       # Formatting helpers
├── App.tsx                 # Main app component
├── main.tsx                # App entry point
└── index.css               # Global styles
```

## 📜 Scripts

```bash
npm run dev       # Start development server
npm run build     # Build for production
npm run preview   # Preview production build
npm run lint      # Run ESLint
npm run format    # Format code with Prettier
```

## 🔗 Backend Integration

The frontend expects the backend API to be running at `http://localhost:8000` (configurable via `VITE_API_BASE_URL` in `.env`).

## 🚧 Development Status

**Phase 1: Foundation** ✅ COMPLETE
- Project scaffolding
- Type definitions
- State management setup
- Basic components
- SSE streaming hook

**Phase 2: Core Chat** 🚧 IN PROGRESS
- Markdown rendering
- Error boundaries
- Loading states

**Phase 3: Session Management** ⏳ PLANNED
- Full session CRUD
- Auto-title
- Session search

**Phase 4: Features** ⏳ PLANNED
- Message actions
- Export functionality
- Settings panel

**Phase 5: Polish** ⏳ PLANNED
- Mobile responsive design
- Accessibility (WCAG 2.1)
- Performance optimization
- Testing

## 📝 License

MIT
