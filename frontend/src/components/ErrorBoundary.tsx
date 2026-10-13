import { Component, type ReactNode } from "react";

/** Keeps the rest of the application usable if a viewer fails (e.g. no WebGL). */
export default class ErrorBoundary extends Component<{ children: ReactNode; label: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error)
      return (
        <div className="empty">
          <b>{this.props.label} could not be displayed.</b>
          <div className="small">{this.state.error.message || String(this.state.error)}</div>
          <div className="small muted">The 3D view needs WebGL. Try the 2D planning map, or another browser.</div>
          <button className="secondary" onClick={() => this.setState({ error: null })}>Retry</button>
        </div>
      );
    return this.props.children;
  }
}
