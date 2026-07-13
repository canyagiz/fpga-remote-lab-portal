// A stable, distinct color per username (same person always gets the same
// color, different people almost always get visibly different ones) -
// used for Calendar pins and profile avatar placeholders alike.
export function colorForUsername(username: string): string {
  let hash = 0;
  for (let i = 0; i < username.length; i++) {
    hash = username.charCodeAt(i) + ((hash << 5) - hash);
    hash |= 0;
  }
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue}, 65%, 42%)`;
}
