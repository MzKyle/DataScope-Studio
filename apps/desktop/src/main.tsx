import React, { Component, type ErrorInfo, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { AppProviders } from "./app/AppProviders";
import {
  installGlobalDiagnosticHandlers,
  logDiagnosticError
} from "./diagnostic-log";
import "./styles.css";

installGlobalDiagnosticHandlers();

class AppRenderBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("DataScope Studio render failed", error, info);
    logDiagnosticError("frontend.react_boundary", error, {
      component_stack: info.componentStack?.slice(0, 4_000)
    });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="render-error">
        <section>
          <h1>DataScope Studio 显示异常</h1>
          <p>{this.state.error.message}</p>
          <button type="button" onClick={() => window.location.reload()}>
            重新加载
          </button>
        </section>
      </main>
    );
  }
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AppRenderBoundary>
      <AppProviders>
        <App />
      </AppProviders>
    </AppRenderBoundary>
  </React.StrictMode>
);
