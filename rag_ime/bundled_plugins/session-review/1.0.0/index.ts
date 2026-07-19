export default function registerSessionReview(pi: {
  registerCommand?: (name: string, handler: () => unknown) => void;
}) {
  pi.registerCommand?.("session-review", () => ({
    title: "Session review",
    instruction: "Review the current session using only evidenced outcomes.",
  }));
}
