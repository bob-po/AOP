import type { DeployPanel } from "../ui/panel.js";
import type { TaskStore } from "../core/task-store.js";
import type { TaskRecord } from "../types.js";

type PiEvent = {
  type: string;
  toolName?: string;
  isError?: boolean;
  assistantMessageEvent?: { type: string; delta?: string };
  messages?: unknown[];
};

export function bindAgentEvents(
  session: { subscribe: (listener: (event: PiEvent) => void) => () => void },
  opts: {
    panel: DeployPanel;
    store: TaskStore;
    task: TaskRecord;
  },
): () => void {
  let textBuffer = "";

  return session.subscribe((event) => {
    switch (event.type) {
      case "message_update":
        if (event.assistantMessageEvent?.type === "text_delta" && event.assistantMessageEvent.delta) {
          textBuffer += event.assistantMessageEvent.delta;
          if (/[.!?\n]/.test(event.assistantMessageEvent.delta)) {
            const sentence = textBuffer.replace(/\s+/g, " ").trim();
            if (sentence.length > 20) {
              opts.panel.agent(sentence.slice(-180));
              opts.store.appendEvent(opts.task, sentence.slice(-180), "agent");
            }
            textBuffer = "";
          }
        }
        break;
      case "tool_execution_start":
        opts.panel.agent(`Calling tool ${event.toolName}`);
        opts.store.appendEvent(opts.task, `tool_start:${event.toolName}`, "agent");
        break;
      case "tool_execution_end":
        opts.store.appendEvent(
          opts.task,
          `tool_end:${event.toolName}:${event.isError ? "error" : "ok"}`,
          event.isError ? "warn" : "agent",
        );
        break;
      default:
        break;
    }
  });
}
