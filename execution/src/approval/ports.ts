/**
 * Ports for human interaction. The engine never sends credentials, tokens or account identifiers
 * through these: messages are built from trade fields only (see approval/messages.ts).
 */

export interface ApprovalButtons {
  approveData: string;
  rejectData: string;
}

export interface Notifier {
  /** Plain alert to the operator (errors, fills, protection status). */
  alert(text: string): Promise<void>;
  /** Sends an approval request with Approve / Reject buttons; returns the chat message id. */
  requestApproval(text: string, buttons: ApprovalButtons): Promise<number>;
  /** Replaces the buttons of an approval message with a final line (approved, rejected, expired). */
  closeApproval(messageId: number, text: string): Promise<void>;
  /** Stops the button spinner in the Telegram client. Optional. */
  answerCallback?(callbackQueryId: string, text: string): Promise<void>;
}

export interface ApprovalCallback {
  callbackQueryId: string;
  fromUserId: number;
  chatId: number;
  data: string;
  messageId?: number;
}
