import {
  CodeBlock,
  Message,
  MessageContent,
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
  type ToolState,
} from "@actioneer/ads";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMsg, ChatStep } from "../../api";

// A message that's mid-stream: content grows, steps accumulate, `streaming` until done.
export type LiveMsg = ChatMsg & { streaming?: boolean };

// A step is "running" until its summary is filled in ("…" is the placeholder the stream sets on a
// tool_call before the matching tool_result arrives).
function toolState(s: ChatStep): ToolState {
  return s.summary === "…" ? "input-available" : "output-available";
}

// Renders one chat message — user turn, or the assistant's activity (tool steps + SQL) and streamed
// markdown. Shared by the global Chat page and the per-call CallChat panel.
export function Bubble({ msg }: { msg: LiveMsg }) {
  if (msg.role === "user") {
    return (
      <Message from="user">
        <MessageContent>{msg.content}</MessageContent>
      </Message>
    );
  }

  return (
    <Message from="assistant">
      {msg.steps.map((s, i) => {
        const query = s.name === "execute_sql" ? (s.args as { query?: string })?.query : undefined;
        return (
          <Tool key={i}>
            <ToolHeader type={s.name} state={toolState(s)} title={stepLabel(s)} />
            <ToolContent>
              {query
                ? <CodeBlock language="sql" filename="query.sql">{query}</CodeBlock>
                : s.args != null && <ToolInput input={s.args} />}
              {s.summary !== "…" && <ToolOutput output={s.summary} />}
            </ToolContent>
          </Tool>
        );
      })}
      <MessageContent variant="plain">
        <div className="prose">
          {msg.content
            ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            : (msg.streaming && <span className="cursor">▍</span>)}
          {msg.content && msg.streaming && <span className="cursor">▍</span>}
        </div>
      </MessageContent>
    </Message>
  );
}

export function stepLabel(s: ChatStep): string {
  const verb = s.name === "execute_sql" ? "Ran SQL" : s.name;
  return s.summary === "…" ? `${verb === "Ran SQL" ? "Running SQL" : verb}…` : `${verb} · ${s.summary}`;
}
