from __future__ import annotations
from enum import Enum
from pydantic import BaseModel


class EnvVarSpec(BaseModel):
    name: str
    description: str
    required: bool
    default_value: str | None = None
    source: str
    category: str


class RepoAnalysisResult(BaseModel):
    repo_path: str
    language: str
    package_manager: str
    entry_point: str
    install_commands: list[str]
    config_files_found: list[str]
    readme_summary: str
    base_image_suggestion: str
    transport_type: str
    exposed_port: int | None = None
    extra_system_deps: list[str]
    required_env_vars: list[EnvVarSpec]
    optional_env_vars: list[EnvVarSpec]
    env_file_template: str
    secrets_risk: str
    confidence: float
    notes: list[str]


class DockerfileSpec(BaseModel):
    dockerfile_content: str
    env_vars_to_inject: list[str]
    expected_transport: str
    exposed_ports: list[int]
    entrypoint: list[str]
    notes: list[str]


class BuildResult(BaseModel):
    success: bool
    image_tag: str
    build_log: str
    error_summary: str | None = None


class TestResult(BaseModel):
    container_started: bool
    startup_log: str
    mcp_handshake_ok: bool
    error_summary: str | None = None
    missing_secrets: list[str]


class FinalOutput(BaseModel):
    success: bool
    repo_path: str
    dockerfile_content: str
    env_template: str
    image_tag: str
    transport_type: str
    required_secrets: list[EnvVarSpec]
    mcp_handshake_tested: bool
    startup_command: str
    notes: list[str]


class PipelineState(Enum):
    INIT = "init"
    REPO_ANALYSIS = "repo_analysis"
    DOCKERFILE_GEN = "dockerfile_gen"
    BUILD_TEST = "build_test"
    FIXING = "fixing"
    DONE = "done"
    FAILED = "failed"


class PipelineContext(BaseModel):
    state: PipelineState = PipelineState.INIT
    repo_path: str
    work_dir: str
    repo_analysis: RepoAnalysisResult | None = None
    dockerfile_spec: DockerfileSpec | None = None
    build_result: BuildResult | None = None
    test_result: TestResult | None = None
    fix_attempts: int = 0
    max_fix_attempts: int = 3
    error_history: list[str] = []
