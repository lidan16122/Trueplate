/** Moves keyboard focus as well as scroll position, so the next Tab stays in the page content. */
export function SkipToContent() {
  return (
    <a
      href="#main-content"
      className="skip-to-content"
      onClick={() => document.getElementById("main-content")?.focus()}
    >
      Skip to content
    </a>
  );
}
