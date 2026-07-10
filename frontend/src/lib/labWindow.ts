// A fixed window *name* (not "_blank") makes the browser reuse/refocus the
// same tab on repeat calls instead of opening a new one - so clicking
// Access twice (from the same reservation, or from both the Labs and
// Dashboard pages) can't ever result in two tabs controlling the same
// physical board at once.
//
// Deliberately no "noopener": per spec, noopener puts the new window in
// its own unrelated browsing context group, which makes named-target
// reuse fall back to always-open-a-new-tab (defeating the point here).
// Safe to omit - the URL is always our own same-origin /hw/{labId}/...
// proxy path (see routers/hardware_proxy.py), never third-party.
export function openLabWindow(labId: number, url: string) {
  window.open(url, `lab-session-${labId}`);
}
