import { Component, type ErrorInfo, type ReactNode } from "react";

interface State { hasError: boolean }

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State { return { hasError: true }; }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Application render error", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return <main className="fatal-error"><h1>Something went wrong</h1><p>Reload the page. No forecast data was changed.</p></main>;
    }
    return this.props.children;
  }
}
