import asyncio
import os
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Static, Header, Footer, RichLog
from textual.containers import Vertical, Horizontal
from textual import work

from tui.utils.docker_manager import generate_env_file, run_docker_compose_up

class DeploymentScreen(Screen):
    """Handles configuring the environment and launching Docker."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(classes="panel", id="deploy-panel"):
            yield Static("🚀 Deployment", classes="title")
            yield Static("", id="deploy-summary")
            
            with Horizontal(id="deploy-action-buttons"):
                yield Button("Launch Pipeline", variant="primary", id="launch_btn")
                yield Button("Finish Setup", id="finish_btn", disabled=True)
                
            # RichLog acts like a robust terminal window inside Textual
            yield RichLog(id="docker-log", highlight=True, markup=True, auto_scroll=True)
            
        yield Footer()

    def on_mount(self) -> None:
        self.update_summary()

    def update_summary(self) -> None:
        state = self.app.state
        summary = (
            f"Ready to deploy!\n\n"
            f"[bold cyan]Selected Model:[/bold cyan] {state.model_name}\n"
            f"[bold cyan]Backend:[/bold cyan] {state.backend}\n"
            f"[bold cyan]GPU Tier:[/bold cyan] {state.assigned_tier}\n\n"
            "Click 'Launch Pipeline' to write the .env file and start the Docker containers."
        )
        self.query_one("#deploy-summary", Static).update(summary)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "launch_btn":
            self.query_one("#launch_btn", Button).disabled = True
            self.start_deployment()
        elif event.button.id == "finish_btn":
            self.app.exit(message="Setup completed successfully! Check daemon.log for background status.")

    @work
    async def start_deployment(self) -> None:
        """
        Writes the .env, runs Ollama, pulls necessary models,
        and runs docker-compose for the remaining services.
        """
        log = self.query_one("#docker-log", RichLog)
        state = self.app.state
        from tui.utils.docker_manager import DockerManager
        docker_manager = DockerManager()

        def log_callback(msg: str) -> None:
            log.write(msg.rstrip("\n"))

        # Determine the project root assuming the script is run from the root
        project_root = os.getcwd()
        env_path = os.path.join(project_root, ".env")

        log.write("[bold yellow]Generating .env file...[/bold yellow]")
        try:
            generate_env_file(state, filepath=env_path)
            log.write(f"[bold green]Successfully wrote .env to {env_path}[/bold green]")
        except Exception as e:
            log.write(f"[bold red]Failed to write .env:[/bold red] {e}")
            self.query_one("#launch_btn", Button).disabled = False
            return

        # ── Pre-flight cleanup ────────────────────────────────────
        # Remove the broken named volume from previous failed attempts
        # (it was a directory mounted onto a file path, causing OCI errors).
        log.write("\n[dim]Cleaning up stale volumes...[/dim]")
        cleanup_proc = await asyncio.create_subprocess_shell(
            "docker volume rm smart-db_anythingllm_env 2>/dev/null || true",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=project_root,
        )
        await cleanup_proc.communicate()

        # Ensure .env exists as a real file on the host.  Docker will
        # auto-create it as a *directory* if the source doesn't exist,
        # which causes an OCI runtime mount error.
        if not os.path.isfile(env_path):
            log.write("[dim]Creating empty .env placeholder...[/dim]")
            open(env_path, "a").close()

        # ── Step A: Always spin up Ollama ────────────────────────
        log.write("\n[bold yellow]Starting local Ollama container...[/bold yellow]")
        status = await docker_manager.ensure_ollama_running(cwd=project_root, log_callback=log_callback)
        if not status.success:
            log.write(f"\n[bold red]❌ Failed to start Ollama:[/bold red] {status.message}")
            self.query_one("#launch_btn", Button).disabled = False
            return
        log.write("[bold green]✅ Ollama is ready![/bold green]")

        # ── Step B: Pull bge-m3 embedding model ──────────────────
        log.write("\n[bold yellow]Pulling bge-m3 embedding model...[/bold yellow]")
        bge_status = await docker_manager.pull_model(model_name="bge-m3", log_callback=log_callback)
        if not bge_status.success:
            log.write("\n[bold red]Критическая ошибка: Не удалось запустить локальный векторный движок bge-m3[/bold red]")
            log.write(f"[dim]{bge_status.message}[/dim]")
            self.query_one("#launch_btn", Button).disabled = False
            return
        log.write("[bold green]✅ bge-m3 is ready![/bold green]")

        # ── Step C: Conditional pull for text model ──────────────
        backend = getattr(state, "llm_provider", getattr(state, "backend", "ollama"))
        if backend == "ollama":
            model_name = getattr(state, "model_name", "")
            if model_name:
                log.write(f"\n[bold yellow]Pulling LLM: {model_name}...[/bold yellow]")
                llm_status = await docker_manager.pull_model(model_name=model_name, log_callback=log_callback)
                if not llm_status.success:
                    log.write(f"\n[bold red]❌ Failed to pull {model_name}:[/bold red] {llm_status.message}")
                    self.query_one("#launch_btn", Button).disabled = False
                    return
                log.write(f"[bold green]✅ {model_name} is ready![/bold green]")
        else:
            log.write(f"\n[bold cyan]Backend is '{backend}' — skipping local text model download.[/bold cyan]")

        # ── Start remaining services ─────────────────────────────
        services = ["anythingllm"]
        log.write(f"\n[bold yellow]Starting Docker services: {', '.join(services)}...[/bold yellow]")

        try:
            async for line in run_docker_compose_up(cwd=project_root, services=services):
                log.write(line)
        except Exception as e:
            log.write(f"\n[bold red]❌ Docker compose failed:[/bold red] {e}")
            self.query_one("#launch_btn", Button).disabled = False
            return

        log.write("\n[bold yellow]Launching System Orchestrator in background...[/bold yellow]")

        import subprocess
        try:
            subprocess.Popen(
                "nohup python3 orchestrator.py > daemon.log 2>&1 &",
                shell=True,
                start_new_session=True,
                cwd=project_root
            )
            log.write("\n[bold green]✅ Orchestrator dispatched successfully![/bold green]")
            log.write("[dim]Check daemon.log for background status.[/dim]")
            
            self.query_one("#finish_btn", Button).disabled = False
            self.query_one("#deploy-summary", Static).update(
                "[bold green]All systems go![/bold green] Click 'Finish Setup' to exit the wizard."
            )

        except Exception as e:
            log.write(f"\n[bold red]❌ Deployment failed:[/bold red] {e}")
            self.query_one("#launch_btn", Button).disabled = False
