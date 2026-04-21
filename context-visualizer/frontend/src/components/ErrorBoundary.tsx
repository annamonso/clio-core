import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  label?: string;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="p-6 bg-elevate rounded-xl border border-red-800/60 text-red-300 text-sm space-y-2">
          <div className="font-semibold">
            {this.props.label ?? "Component"} failed to render
          </div>
          <div className="font-mono text-xs text-red-400 bg-canvas rounded p-3 overflow-x-auto">
            {this.state.error.message}
          </div>
          <button
            className="text-xs text-fg-secondary underline"
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
