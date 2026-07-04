from __future__ import annotations

import argparse
import os
from pathlib import Path

from .config import (
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_FAKE_MODEL,
    DEFAULT_MAX_NEW_TOKENS,
    DEFAULT_MAX_STEPS,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROVIDER,
    env_list,
    env_or,
    load_dotenv,
)
from .features.memory import LayeredMemory
from .providers import (
    AnthropicCompatibleModelClient,
    FakeModelClient,
    ModelClient,
    OllamaModelClient,
    OpenAICompatibleModelClient,
)
from .run_store import RunStore, SessionStore
from .runtime import Pico
from .workspace import WorkspaceContext


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LabFlow Agent local scientific-data workflow assistant")
    parser.add_argument("prompt", nargs="?", help="User request for one-shot mode")
    parser.add_argument("--cwd", default=".", help="Workspace directory")
    parser.add_argument("--provider", choices=["fake", "ollama", "openai-compatible", "anthropic-compatible"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--host", default=None, help="Alias for Ollama host")
    parser.add_argument("--api-key-env", default=None, help="Environment variable containing provider API key")
    parser.add_argument("--approval", choices=["never", "ask", "auto"], default="ask")
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--resume", default=None, help="Session id or 'latest'")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--max-new-tokens", type=int, default=DEFAULT_MAX_NEW_TOKENS)
    parser.add_argument("--repl", action="store_true")
    parser.add_argument("--fake-script", default=None, help="Fake model responses separated by ||")
    parser.add_argument(
        "--no-planner",
        action="store_true",
        help="Disable the suggested-plan guidance layer",
    )
    return parser


def effective_provider(args: argparse.Namespace) -> str:
    return args.provider or env_or(DEFAULT_PROVIDER, "PICO_PROVIDER")


def effective_model(args: argparse.Namespace, provider: str) -> str:
    if args.model:
        return args.model
    if provider == "ollama":
        return env_or(DEFAULT_OLLAMA_MODEL, "PICO_OLLAMA_MODEL")
    if provider == "openai-compatible":
        return env_or(DEFAULT_OPENAI_MODEL, "PICO_OPENAI_MODEL")
    if provider == "anthropic-compatible":
        return env_or(DEFAULT_ANTHROPIC_MODEL, "PICO_ANTHROPIC_MODEL")
    return DEFAULT_FAKE_MODEL


def build_model_client(args: argparse.Namespace) -> ModelClient:
    provider = effective_provider(args)
    model = effective_model(args, provider)
    if provider == "fake":
        script = args.fake_script.split("||") if args.fake_script else None
        return FakeModelClient(script=script, model=model)
    if provider == "ollama":
        base_url = args.host or args.base_url or env_or(DEFAULT_OLLAMA_HOST, "PICO_OLLAMA_HOST", "OLLAMA_HOST")
        return OllamaModelClient(model=model, base_url=base_url)
    if provider == "openai-compatible":
        base_url = args.base_url or env_or(DEFAULT_OPENAI_BASE_URL, "PICO_OPENAI_API_BASE", "OPENAI_BASE_URL")
        key_name = args.api_key_env or "PICO_OPENAI_API_KEY"
        api_key = os.environ.get(key_name) or os.environ.get("OPENAI_API_KEY")
        return OpenAICompatibleModelClient(model=model, base_url=base_url, api_key=api_key)
    if provider == "anthropic-compatible":
        base_url = args.base_url or env_or(DEFAULT_ANTHROPIC_BASE_URL, "PICO_ANTHROPIC_API_BASE", "ANTHROPIC_BASE_URL")
        key_name = args.api_key_env or "PICO_ANTHROPIC_API_KEY"
        api_key = os.environ.get(key_name) or os.environ.get("ANTHROPIC_API_KEY")
        return AnthropicCompatibleModelClient(model=model, base_url=base_url, api_key=api_key)
    raise ValueError(f"unknown provider: {provider}")


def build_agent(args: argparse.Namespace) -> Pico:
    cwd = Path(args.cwd).resolve()
    load_dotenv(cwd)
    workspace = WorkspaceContext.build(cwd)
    session_store = SessionStore(workspace.repo_root)
    run_store = RunStore(workspace.repo_root)
    model_client = build_model_client(args)
    secret_names = env_list("PICO_SECRET_ENV_NAMES")
    if args.resume:
        session_id = session_store.latest() if args.resume == "latest" else args.resume
        if session_id:
            session = session_store.load(session_id)
            return Pico.from_session(
                session,
                workspace=workspace,
                model_client=model_client,
                session_store=session_store,
                run_store=run_store,
                approval=args.approval,
                read_only=args.read_only,
                max_steps=args.max_steps,
                max_new_tokens=args.max_new_tokens,
                secret_env_names=secret_names,
                use_planner=not args.no_planner,
            )
    return Pico(
        workspace=workspace,
        model_client=model_client,
        session_store=session_store,
        run_store=run_store,
        memory=LayeredMemory(),
        approval=args.approval,
        read_only=args.read_only,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        secret_env_names=secret_names,
        use_planner=not args.no_planner,
    )


def run_repl(agent: Pico) -> int:
    print("LabFlow Agent REPL. Type /help for commands, /exit to quit.")
    while True:
        try:
            line = input("labflow> ").strip()
        except EOFError:
            print()
            return 0
        if not line:
            continue
        if line == "/exit":
            return 0
        if line == "/help":
            print("Commands: /help, /session, /memory, /exit")
            continue
        if line == "/session":
            print(agent.session_id)
            continue
        if line == "/memory":
            print(agent.memory.render(agent.workspace.repo_root) or "(empty)")
            continue
        print(agent.ask(line))


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    agent = build_agent(args)
    if args.repl or not args.prompt:
        return run_repl(agent)
    answer = agent.ask(args.prompt)
    if answer:
        print(answer)
    return 0
