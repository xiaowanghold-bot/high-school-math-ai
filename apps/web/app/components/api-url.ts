/**
 * Long model/OCR requests must not pass through the Next development rewrite:
 * that proxy closes slow responses at roughly 30 seconds although the API keeps
 * running (and the model call keeps consuming tokens).
 */
export function longTaskApiUrl(path: string): string {
  const configured = process.env.NEXT_PUBLIC_MATH_AI_API_URL?.replace(/\/$/, "");
  if (configured) return `${configured}${path}`;
  if (typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname)) {
    return `http://${window.location.hostname}:8000${path}`;
  }
  return path;
}
