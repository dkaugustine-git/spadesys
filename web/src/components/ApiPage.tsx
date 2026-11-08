/** FastAPI's built-in docs, inside Spadesys. Every button in this app calls one of these endpoints. */
export function ApiPage() {
  return (
    <main className="framed">
      <div className="framed-bar">
        <span className="muted small">
          Every button in Spadesys calls one of these. Open one and click <b>Try it out</b> to call it yourself.
        </span>
        <span className="spacer" />
        <a className="btn" href="/api/openapi.json" target="_blank" rel="noreferrer">OpenAPI file</a>
        <a className="btn" href="/api/docs" target="_blank" rel="noreferrer">Open in a new window</a>
      </div>
      <iframe className="framed-frame" src="/api/docs" title="Spadesys API" />
    </main>
  );
}
