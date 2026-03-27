export async function sendProactiveCard(
  card: Record<string, unknown>,
): Promise<{ ok: boolean; messageId?: string }> {
  // Stub: will be wired to Bot Framework adapter in Plan 06-02
  console.log(
    "[proactive] Card ready to send (stub)",
    JSON.stringify(card).substring(0, 100),
  );
  return { ok: true, messageId: "stub" };
}
