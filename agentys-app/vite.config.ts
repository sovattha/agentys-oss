import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import type { Plugin } from "vite"
import { execFileSync, spawn, type ChildProcess } from "child_process"
import { readFileSync } from "fs"
import net from "net"

// Résolution de la version affichée dans Paramètres → Général.
// Priorité : VITE_APP_VERSION (CI override) → <pkg.version>-dev.<short_sha> → pkg.version
function resolveAppVersion(): string {
  if (process.env.VITE_APP_VERSION) {
    return process.env.VITE_APP_VERSION
  }
  const pkgPath = path.resolve(__dirname, "package.json")
  const pkg = JSON.parse(readFileSync(pkgPath, "utf-8")) as { version: string }
  try {
    const sha = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
      cwd: __dirname,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim()
    return sha ? `${pkg.version}-dev.${sha}` : pkg.version
  } catch {
    return pkg.version
  }
}

const APP_VERSION = resolveAppVersion()

// Plugin: démarre le backend Python automatiquement avec `yarn dev`
function pythonBackendPlugin(): Plugin {
  let backendProcess: ChildProcess | null = null

  return {
    name: "python-backend",
    apply: "serve",
    configureServer() {
      const backendDir = path.resolve(__dirname, "..")
      // Démarre le backend uniquement s'il n'est pas déjà en cours
      const probe = net.createConnection({ port: 5050, host: "127.0.0.1" })
      probe.on("connect", () => {
        probe.destroy()
        console.log("[backend] already running on :5050, skipping auto-start")
      })
      probe.on("error", () => {
        probe.destroy()
        console.log("[backend] starting Python API on :5050...")
        backendProcess = spawn("python", ["run_api.py"], {
          cwd: backendDir,
          stdio: "inherit",
          shell: true,
        })
        backendProcess.on("error", (err) => {
          console.error("[backend] failed to start:", err.message)
        })
      })

      // Arrêt propre du backend quand Vite s'arrête
      const cleanup = () => {
        if (backendProcess) {
          console.log("[backend] stopping Python API...")
          backendProcess.kill()
          backendProcess = null
        }
      }
      process.on("exit", cleanup)
      process.on("SIGINT", cleanup)
      process.on("SIGTERM", cleanup)
    },
  }
}

// Plugin: relaxe la CSP en dev UNIQUEMENT pour autoriser le backend local.
// La CSP d'index.html (connect-src 'self' + domaines prod) est calibrée pour
// la prod web ; en dev elle bloque les fetchs absolus vers :5050, ce qui
// casse le mode VITE_API_URL=http://127.0.0.1:5050 — le mode pour lequel
// toute la suite e2e a été écrite (ses mocks interceptent les origins :5050).
// `apply: 'serve'` garantit que le build prod conserve la CSP stricte.
function cspDevRelaxPlugin(): Plugin {
  return {
    name: "csp-dev-relax",
    apply: "serve",
    transformIndexHtml(html) {
      return html.replace(
        /connect-src 'self'/,
        "connect-src 'self' http://localhost:5050 http://127.0.0.1:5050 ws://localhost:5050 ws://127.0.0.1:5050",
      )
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  plugins: [react(), tailwindcss(), pythonBackendPlugin(), cspDevRelaxPlugin()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 1420,
    strictPort: true,
    allowedHosts: [".trycloudflare.com", ".loca.lt"],
    // Proxy Vite → backend Python — évite le blocage CORS (localhost:1420 → 127.0.0.1:5050)
    // En production Tauri il n'y a pas de CORS (même hôte), donc ce proxy n'est actif qu'en dev.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5050',
        changeOrigin: true,
      },
      '/socket.io': {
        target: 'http://127.0.0.1:5050',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  // OPTIMIZATION: Code splitting for better initial load
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Locale JSONs: group all of one language's namespaces into a
          // single `locale-<lng>` chunk. Without this, each (lang, ns) pair
          // becomes its own micro-chunk → 52 HTTP requests on language load.
          // Match against the source dir, not node_modules (these are first-party).
          const localeMatch = id.match(/[\\/]src[\\/]i18n[\\/]locales[\\/]([a-z]{2})[\\/]/)
          if (localeMatch) {
            return `locale-${localeMatch[1]}`
          }
          if (!id.includes("node_modules")) {
            return undefined
          }
          if (/[\\/]node_modules[\\/](react|react-dom)[\\/]/.test(id)) {
            return "vendor-react"
          }
          if (/[\\/]node_modules[\\/]socket\.io-client[\\/]/.test(id)) {
            return "vendor-socket"
          }
          if (/[\\/]node_modules[\\/]@tiptap[\\/]/.test(id)) {
            return "vendor-editor"
          }
          if (/[\\/]node_modules[\\/](class-variance-authority|clsx|tailwind-merge)[\\/]/.test(id)) {
            return "vendor-ui"
          }
          return undefined
        },
      },
    },
    // Warn if chunks exceed 500KB
    chunkSizeWarningLimit: 500,
  },
})
