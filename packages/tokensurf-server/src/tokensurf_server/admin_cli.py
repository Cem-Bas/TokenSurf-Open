from __future__ import annotations

import re
import subprocess

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session
from tokensurf.core.ids import new_id

from tokensurf_server.models import Project, ProjectApiKey, User
from tokensurf_server.secrets_service import set_secret
from tokensurf_server.security import generate_api_key, hash_key, hash_password, key_prefix

app = typer.Typer(help="TokenSurf Server admin")


def _get_session() -> Session:
    from tokensurf_server.db import get_sessionmaker

    return get_sessionmaker()()


@app.command()
def migrate() -> None:
    """Run Alembic migrations to head."""
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@app.command("create-project")
def create_project(
    name: str,
    slug: str = typer.Option(None, help="URL-safe slug; derived from name if omitted"),
) -> None:
    """Insert a project and print its id and slug."""
    if slug is None:
        slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")

    project = Project(id=new_id(), name=name, slug=slug)
    with _get_session() as session:
        session.add(project)
        session.commit()
        typer.echo(f"id={project.id} slug={project.slug}")


@app.command("create-key")
def create_key(
    project_slug: str,
    label: str = typer.Option("", help="Human-readable label for this key"),
) -> None:
    """Mint an ingest API key; print the raw key once, store only its hash."""
    with _get_session() as session:
        project = session.scalar(select(Project).where(Project.slug == project_slug))
        if project is None:
            typer.echo(f"Error: project '{project_slug}' not found", err=True)
            raise typer.Exit(code=1)

        raw = generate_api_key()
        pak = ProjectApiKey(
            id=new_id(),
            project_id=project.id,
            key_hash=hash_key(raw),
            key_prefix=key_prefix(raw),
            label=label or None,
        )
        session.add(pak)
        session.commit()

    typer.echo(raw)


@app.command("create-user")
def create_user(
    email: str,
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=False),
) -> None:
    """Create a dashboard user with a hashed password; exits 1 if email is already taken."""
    user = User(id=new_id(), email=email, password_hash=hash_password(password))
    with _get_session() as session:
        try:
            session.add(user)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    typer.echo(f"user {email} created")


@app.command("create-gate")
def create_gate(
    project_slug: str,
    name: str,
    metric: str,
    threshold: float,
    comparison: str = typer.Option("gte", "--comparison", help="lt|lte|gt|gte"),
    scorer: str = typer.Option("", "--scorer", help="Scorer name (required for scorer_pass_rate)"),
) -> None:
    """Insert a QualityGate for the project and print its id."""
    from tokensurf_server.models import QualityGate

    with _get_session() as session:
        project = session.scalar(select(Project).where(Project.slug == project_slug))
        if project is None:
            typer.echo(f"Error: project '{project_slug}' not found", err=True)
            raise typer.Exit(code=1)

        gate = QualityGate(
            id=new_id(),
            project_id=project.id,
            name=name,
            metric=metric,
            scorer=scorer or None,
            comparison=comparison,
            threshold=threshold,
        )
        session.add(gate)
        session.commit()
        typer.echo(gate.id)


@app.command("create-channel")
def create_channel(
    project_slug: str,
    name: str,
    secret: str,
    to: str = typer.Argument(default="", help="Recipient address (email type)"),
    type_: str = typer.Option(..., "--type", help="slack|webhook|email"),
) -> None:
    """Create a NotificationChannel with the secret encrypted at rest; print its id."""
    from tokensurf_server.crypto import encrypt
    from tokensurf_server.models import NotificationChannel

    with _get_session() as session:
        project = session.scalar(select(Project).where(Project.slug == project_slug))
        if project is None:
            typer.echo(f"Error: project '{project_slug}' not found", err=True)
            raise typer.Exit(code=1)

        config = {"to": to} if to else None
        channel = NotificationChannel(
            id=new_id(),
            project_id=project.id,
            type=type_,
            name=name,
            secret_enc=encrypt(secret),
            config=config,
        )
        session.add(channel)
        session.commit()
        typer.echo(channel.id)


@app.command("create-secret")
def create_secret(project_slug: str, provider: str, secret: str) -> None:
    """Store an encrypted judge/provider key for a project (upsert by provider)."""
    with _get_session() as session:
        project = session.scalar(select(Project).where(Project.slug == project_slug))
        if project is None:
            typer.echo(f"Error: project '{project_slug}' not found", err=True)
            raise typer.Exit(code=1)
        set_secret(session, project_id=project.id, provider=provider, plaintext=secret)
        session.commit()
    typer.echo(f"secret set for {provider}")
