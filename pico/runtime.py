from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent.intent import detect_intent
from .agent.planner import build_plan, render_plan
from .config import DEFAULT_MAX_ATTEMPTS, DEFAULT_MAX_NEW_TOKENS, DEFAULT_MAX_STEPS, env_or
from .context_manager import build_prompt
from .features.memory import DurableMemoryStore, LayeredMemory
from .prompt_prefix import PromptPrefix, build_prompt_prefix
from .providers import ModelClient, ModelProviderError, ModelRequest
from .run_store import RunStore, SessionStore
from .security import collect_secret_env_names, redact_text, safe_shell_env
from .task_state import TaskState, new_id, now_iso
from .tool_context import ToolContext
from .tool_executor import ToolExecutor
from .tools import ToolResult
from .tools.registry import build_tool_registry
from .workflow_trace import build_run_summary, build_workflow_log, write_workflow_log
from .workspace import WorkspaceContext, resolve_in_workspace


@dataclass
class ParsedOutput:
    kind: str
    payload: Any
    raw: str


@dataclass
class Pico:
    workspace: WorkspaceContext
    model_client: ModelClient
    session_store: SessionStore
    run_store: RunStore
    memory: LayeredMemory = field(default_factory=LayeredMemory)
    history: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: new_id("session"))
    approval: str = "ask"
    read_only: bool = False
    max_steps: int = DEFAULT_MAX_STEPS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
    depth: int = 0
    max_depth: int = 1
    secret_env_names: list[str] = field(default_factory=list)
    last_tool_signature: str | None = None
    prefix: PromptPrefix | None = None
    last_prompt_metadata: dict[str, Any] = field(default_factory=dict)
    current_batch_id: str | None = None
    use_planner: bool = True
    tool_summaries: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_session(
        cls,
        session: dict[str, Any],
        workspace: WorkspaceContext,
        model_client: ModelClient,
        session_store: SessionStore,
        run_store: RunStore,
        **kwargs: Any,
    ) -> Pico:
        return cls(
            workspace=workspace,
            model_client=model_client,
            session_store=session_store,
            run_store=run_store,
            memory=LayeredMemory.from_dict(session.get("memory")),
            history=list(session.get("history", [])),
            session_id=str(session.get("id") or new_id("session")),
            **kwargs,
        )

    def ask(self, user_message: str, stream_callback=None) -> str:
        DurableMemoryStore(self.workspace.repo_root).ensure()
        if not self.secret_env_names:
            self.secret_env_names = collect_secret_env_names()
        self.memory.set_task_summary(user_message)
        self.history.append({"role": "user", "content": user_message})
        task_state = TaskState.create(user_message)
        self.tool_summaries = []
        self.current_batch_id = None
        self.run_store.start_run(task_state)
        self.emit_trace(
            task_state.run_id,
            "run_started",
            {"session_id": self.session_id, "request": user_message},
        )

        final_answer = ""
        max_turns = self.max_steps + self.max_attempts + 1
        parser_retries = 0
        for _ in range(max_turns):
            if task_state.tool_steps > self.max_steps:
                task_state.finish_stopped("step_limit_reached")
                break
            task_state.record_attempt()
            prompt, metadata = self.build_prompt_and_metadata(user_message)
            self.last_prompt_metadata = metadata
            self.emit_trace(task_state.run_id, "prompt_built", metadata)
            try:
                response = self.model_client.complete(
                    ModelRequest(
                        prompt=prompt,
                        max_tokens=self.max_new_tokens,
                        prompt_cache_key=metadata.get("prompt_cache_key"),
                        metadata=metadata,
                    )
                )
            except ModelProviderError as exc:
                task_state.finish_failed("provider_error", str(exc))
                self.emit_trace(task_state.run_id, "model_error", {"error": str(exc)})
                if hasattr(self.model_client, "retry_events"):
                    self.model_client.retry_events.clear()
                break
            self.emit_trace(
                task_state.run_id,
                "model_completed",
                {
                    "provider": response.provider,
                    "model": response.model,
                    "usage": response.usage,
                    "cache": response.cache,
                },
            )
            for evt in getattr(self.model_client, "retry_events", [])[:]:
                self.emit_trace(task_state.run_id, "provider_retry", evt)
            if hasattr(self.model_client, "retry_events"):
                self.model_client.retry_events.clear()
            parsed = self.parse(response.text)
            self.emit_trace(task_state.run_id, "model_parsed", {"kind": parsed.kind})
            if parsed.kind == "final":
                final_answer = str(parsed.payload).strip()
                if stream_callback is not None and hasattr(self.model_client, "complete_stream"):
                    # The model already produced the full text; replay it to the callback.
                    for token in final_answer:
                        stream_callback(token)
                task_state.finish_success(final_answer)
                self.history.append({"role": "assistant", "content": final_answer})
                break
            if parsed.kind == "tool":
                tool_payload = parsed.payload
                tool_name = str(tool_payload.get("name", ""))
                tool_args = dict(tool_payload.get("args") or {})
                tool_started = time.perf_counter()
                result = self.run_tool(tool_name, tool_args)
                duration_seconds = time.perf_counter() - tool_started
                task_state.record_tool(tool_name)
                if "batch_id" in result.metadata:
                    self.current_batch_id = str(result.metadata["batch_id"])
                if result.workspace_changed:
                    for path in result.affected_paths:
                        self.memory.invalidate_file_summary(path)
                    self.refresh_prefix(force=True)
                if tool_name == "read_file" and result.ok and "path" in result.metadata:
                    path = str(result.metadata["path"])
                    self.memory.set_file_summary(
                        path,
                        summarize_observation(result.text),
                        str(result.metadata.get("freshness", "")),
                    )
                for path in result.affected_paths:
                    self.memory.remember_file(path)
                observation = result.to_observation()
                self.history.append({"role": "assistant", "content": parsed.raw})
                self.history.append({"role": "tool", "name": tool_name, "content": observation})
                self.tool_summaries.append(
                    {"name": tool_name, "duration_seconds": duration_seconds, **result.to_dict()}
                )
                self.emit_trace(
                    task_state.run_id,
                    "tool_finished",
                    {
                        "name": tool_name,
                        "input": tool_args,
                        "duration_seconds": duration_seconds,
                        "result": result.to_dict(),
                    },
                )
                if tool_name == "export_workflow_log" and result.ok:
                    self._write_workflow_log_from_trace(
                        task_state.run_id,
                        str(result.metadata.get("batch_id", self.current_batch_id or "")),
                    )
                self.run_store.write_task_state(task_state)
                continue
            # retry: give the model one correction note.
            parser_retries += 1
            if parser_retries >= self.max_attempts:
                task_state.finish_stopped("retry_limit_reached")
                break
            self.history.append({"role": "tool", "name": "parser", "content": str(parsed.payload)})
            self.run_store.write_task_state(task_state)
        else:
            task_state.finish_stopped("retry_limit_reached")

        if task_state.status == "running":
            task_state.finish_stopped("retry_limit_reached")
        self.run_store.write_task_state(task_state)
        report = self.build_report(task_state)
        self.run_store.write_report(task_state.run_id, report)
        self.emit_trace(
            task_state.run_id,
            "run_summary",
            build_run_summary(
                self.tool_summaries,
                task_state.status,
                getattr(self.model_client, "last_metadata", {}),
                self.last_prompt_metadata,
            ),
        )
        self.emit_trace(task_state.run_id, "run_finished", report)
        if self.current_batch_id:
            self._write_workflow_log_from_trace(task_state.run_id, self.current_batch_id)
        self.save_session()
        return final_answer or task_state.final_answer or ""

    def build_prompt_and_metadata(self, user_message: str) -> tuple[str, dict[str, Any]]:
        self.refresh_prefix()
        memory_text = self.memory.render(self.workspace.repo_root, user_message)
        durable_text = DurableMemoryStore(self.workspace.repo_root).read_all(max_chars=1800)
        if durable_text:
            memory_text = (memory_text + "\n\n## Durable memory\n" + durable_text).strip()
        relevant = ""
        history_text = self.render_history()
        suggested_plan = ""
        if self.use_planner:
            plan = build_plan(user_message)
            suggested_plan = render_plan(plan)
            intent = plan.intent
        else:
            intent = detect_intent(user_message).intent
        # Construct the truncation strategy inline (function-local import to avoid
        # any circular import with context_manager) so that PICO_TRUNCATION_STRATEGY=smart
        # is actually honored and carries the detected intent.
        if env_or("priority", "PICO_TRUNCATION_STRATEGY") == "smart":
            from .context_manager import SmartTruncation

            strategy = SmartTruncation(intent=intent)
        else:
            from .context_manager import PriorityTruncation

            strategy = PriorityTruncation()
        return build_prompt(
            self.prefix,
            memory_text,
            relevant,
            history_text,
            user_message,
            suggested_plan=suggested_plan,
            strategy=strategy,
        )  # type: ignore[arg-type]

    def refresh_prefix(self, force: bool = False) -> None:
        if self.prefix is not None and not force:
            current_fingerprint = self.workspace.fingerprint()
            if self.prefix.workspace_fingerprint == current_fingerprint:
                return
        context = self.tool_context()
        registry = build_tool_registry(context)
        self.prefix = build_prompt_prefix(self.workspace, registry)

    def tool_context(self) -> ToolContext:
        return ToolContext(
            root=self.workspace.repo_root,
            path_resolver=lambda raw: resolve_in_workspace(self.workspace.repo_root, raw),
            shell_env_provider=safe_shell_env,
            depth=self.depth,
            max_depth=self.max_depth,
            spawn_delegate=self.spawn_delegate,
        )

    def run_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        context = self.tool_context()
        registry = build_tool_registry(context)
        executor = ToolExecutor(
            registry=registry,
            context=context,
            approval=self.approval,
            read_only=self.read_only,
            approval_callback=self.approve,
            last_signature=self.last_tool_signature,
        )
        result = executor.execute(name, args)
        self.last_tool_signature = executor.last_signature
        return result

    def approve(self, spec: Any, args: dict[str, Any]) -> bool:
        prompt = f"Approve risky tool {spec.name} with args {args}? [y/N] "
        try:
            return input(prompt).strip().lower() in {"y", "yes"}
        except EOFError:
            return False

    def spawn_delegate(self, task: str, max_steps: int) -> ToolResult:
        child = Pico(
            workspace=self.workspace,
            model_client=self.model_client,
            session_store=self.session_store,
            run_store=self.run_store,
            memory=self.memory,
            history=list(self.history),
            session_id=self.session_id,
            approval="never",
            read_only=True,
            max_steps=max_steps,
            max_attempts=max_steps + 1,
            max_new_tokens=self.max_new_tokens,
            depth=self.depth + 1,
            max_depth=self.max_depth,
            secret_env_names=self.secret_env_names,
        )
        answer = child.ask(task)
        return ToolResult(True, answer, metadata={"delegate_depth": child.depth})

    def parse(self, raw: str) -> ParsedOutput:
        raw = raw.strip()
        tool_match = re.search(r"<tool>(.*?)</tool>", raw, re.DOTALL)
        if tool_match:
            body = tool_match.group(1).strip()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                return ParsedOutput(
                    "retry", f"Invalid tool JSON: {exc}. Return valid JSON inside <tool>.", raw
                )
            if not isinstance(payload, dict) or "name" not in payload:
                return ParsedOutput(
                    "retry", "Tool payload must be an object with name and args.", raw
                )
            payload.setdefault("args", {})
            if not isinstance(payload["args"], dict):
                return ParsedOutput("retry", "Tool args must be an object.", raw)
            return ParsedOutput("tool", payload, raw)
        final_match = re.search(r"<final>(.*?)</final>", raw, re.DOTALL)
        if final_match:
            return ParsedOutput("final", final_match.group(1), raw)
        if raw:
            return ParsedOutput("final", raw, raw)
        return ParsedOutput("retry", "Empty model response. Return <tool> or <final>.", raw)

    def render_history(self, max_messages: int = 20) -> str:
        lines = []
        for item in self.history[-max_messages:]:
            role = item.get("role", "unknown")
            name = item.get("name")
            label = f"{role}:{name}" if name else role
            lines.append(f"## {label}\n{item.get('content', '')}")
        return "\n\n".join(lines)

    def emit_trace(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        safe_payload = json.loads(json.dumps(payload, default=str))
        text = json.dumps(safe_payload, ensure_ascii=False)
        redacted = json.loads(redact_text(text, self.secret_env_names))
        self.run_store.append_trace(
            run_id,
            {
                "id": new_id("evt"),
                "type": event_type,
                "created_at": now_iso(),
                "run_id": run_id,
                "payload": redacted,
            },
        )

    def _write_workflow_log_from_trace(self, run_id: str, batch_id: str) -> Path | None:
        if not batch_id:
            return None
        trace_file = self.run_store.run_dir(run_id) / "trace.jsonl"
        log = build_workflow_log(trace_file, batch_id, run_id, self.session_id)
        return write_workflow_log(self.workspace.repo_root, batch_id, log)

    def build_report(self, task_state: TaskState) -> dict[str, Any]:
        return {
            "run_id": task_state.run_id,
            "task_id": task_state.task_id,
            "session_id": self.session_id,
            "status": task_state.status,
            "stop_reason": task_state.stop_reason,
            "final_answer": task_state.final_answer,
            "attempts": task_state.attempts,
            "tool_steps": task_state.tool_steps,
            "prompt_metadata": self.last_prompt_metadata,
            "model_metadata": getattr(self.model_client, "last_metadata", {}),
            "tool_summary": self.tool_summaries,
        }

    def save_session(self) -> None:
        self.session_store.save(
            {
                "id": self.session_id,
                "workspace_root": str(self.workspace.repo_root),
                "history": self.history,
                "memory": self.memory.to_dict(),
            }
        )


def summarize_observation(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    return compact[:limit]
