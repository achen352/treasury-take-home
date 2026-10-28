"""The deploy configuration: Fly.io, deployed by CI only after the checks pass."""

import re
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
FLY: dict[str, Any] = tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))
CI: dict[str, Any] = yaml.safe_load(
    (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
)


def test_fly_builds_our_dockerfile_and_runs_it_in_virginia() -> None:
    assert FLY["primary_region"] == "iad"  # close to the AI provider's US servers
    assert FLY["build"]["dockerfile"] == "Dockerfile"


def test_fly_serves_https_checks_health_and_suspends_when_idle() -> None:
    service = FLY["http_service"]

    assert service["internal_port"] == 8000
    assert service["force_https"] is True
    assert service["auto_stop_machines"] == "suspend"
    assert service["auto_start_machines"] is True
    assert service["min_machines_running"] == 0
    assert any(check["path"] == "/healthz" for check in service["checks"])


def test_fly_runs_one_small_shared_machine() -> None:
    (vm,) = FLY["vm"]

    assert vm["size"] == "shared-cpu-1x"
    assert vm["memory"] == "512mb"


def test_fly_runs_full_mode_with_openai_and_trusts_only_its_own_client_header() -> None:
    env = FLY["env"]

    assert env["EXTRACTOR_MODE"] == "dual"
    assert env["LLM_BASE_URL"] == "https://api.openai.com/v1"
    assert env["LLM_MODEL"] == "gpt-5.4-mini"
    assert env["LLM_REASONING_EFFORT"] == "low"
    assert env["CLIENT_IP_HEADER"] == "fly-client-ip"
    assert env["REQUIRE_ACCESS_CODE"] == "true"  # the site won't start open


def test_no_secret_lives_in_the_deploy_configuration() -> None:
    text = (ROOT / "fly.toml").read_text(encoding="utf-8")

    for name in ("LLM_API_KEY", "ACCESS_CODE_SHA256", "SMOKE_ACCESS_CODE"):
        assert name not in FLY["env"]
    assert not re.search(r"sk-[A-Za-z0-9]", text)


def test_the_render_configuration_is_gone() -> None:
    assert not (ROOT / "render.yaml").exists()


def test_ci_deploys_to_fly_only_from_main_after_the_tests_and_container_checks_pass() -> None:
    deploy = CI["jobs"]["deploy"]
    steps = deploy["steps"]

    assert {"test", "container"} <= set(deploy["needs"])
    assert "refs/heads/main" in deploy["if"] and "push" in deploy["if"]
    assert any(
        re.fullmatch(r"superfly/flyctl-actions/setup-flyctl@[0-9a-f]{40}", step.get("uses", ""))
        for step in steps
    )
    deploy_step = next(step for step in steps if "flyctl deploy" in step.get("run", ""))
    assert "--remote-only" in deploy_step["run"]
    # A reference to the GitHub secret, not a token.
    assert deploy_step["env"]["FLY_API_TOKEN"] == "${{ secrets.FLY_API_TOKEN }}"  # noqa: S105
