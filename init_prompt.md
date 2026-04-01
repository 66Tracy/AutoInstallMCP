### FIRST: Read the Project Specification

Start by reading `app_spec.txt` in your working directory. This file contains
the complete specification for the MCP Auto-Installer agent system. Read it
carefully before proceeding — pay special attention to:
- The 3-agent architecture (RepoAnalysisAgent → DockerfileAgent → BuildTestAgent)
- The fix loop between DockerfileAgent and BuildTestAgent
- The data schemas (RepoAnalysisResult, DockerfileSpec, BuildResult, TestResult)
- The tool specifications (file_tools, docker_tools)

### CRITICAL FIRST TASK: Create test_plan.json

Based on `app_spec.txt`, create a file called `test_plan.json`. This file defines
every verifiable checkpoint across all implementation steps. It is the single
source of truth for what needs to be built and whether it works.

**Format:**
```json
[
  {
    "id": "infra-01",
    "stage": "1-infrastructure",
    "component": "config",
    "description": "config.py loads LLM_API_KEY, LLM_MODEL, LLM_BASE_URL from .env via python-dotenv",
    "verification": [
      "Create a .env file with test values for LLM_API_KEY, LLM_MODEL, LLM_BASE_URL",
      "Import config module",
      "Assert config.LLM_API_KEY == the test value",
      "Assert config.LLM_MODEL == the test value",
      "Assert config.LLM_BASE_URL == the test value or None when absent"
    ],
    "passes": false
  },
  {
    "id": "tool-03",
    "stage": "2-tools",
    "component": "docker_tools",
    "description": "docker.from_env() successfully connects to local Docker Engine",
    "verification": [
      "Call docker.from_env().ping()",
      "Assert returns True without ConnectionError"
    ],
    "passes": false
  }
]
```

**Stages** (map to implementation steps in app_spec.txt):
- `1-infrastructure` — config, data_structures, schemas, BaseAgent, ModelClient
- `2-tools` — file_tools, docker_tools
- `3-repo-analysis-agent` — RepoAnalysisAgent with prompts and structured output
- `4-dockerfile-agent` — DockerfileAgent generate() and fix() methods
- `5-build-test-agent` — BuildTestAgent build and test phases
- `6-orchestrator` — Pipeline state machine, fix loop, FinalOutput assembly, CLI
- `7-e2e` — End-to-end tests against C:\work_dir\testing_projects\python-sdk

**Requirements for test_plan.json:**
- Cover every component, tool function, agent, and pipeline path described in app_spec.txt
- Each checkpoint must have concrete, executable verification steps
- Include both unit-level checks (e.g., "read_file returns content of a known file") and
  integration checks (e.g., "RepoAnalysisAgent produces valid RepoAnalysisResult for python-sdk repo")
- Stage 7 (e2e) must include the full happy path AND the fix-loop path
- ALL checkpoints start with `"passes": false`
- Order by stage, then by dependency (foundational checks first within each stage)

**CRITICAL INSTRUCTION:**
IT IS CATASTROPHIC TO REMOVE OR EDIT CHECKPOINTS IN FUTURE SESSIONS.
Checkpoints can ONLY be marked as passing (change `"passes": false` to `"passes": true`).
Never remove checkpoints, never edit descriptions, never modify verification steps.

### SECOND TASK: Create init.sh

Create `init.sh` — a script that sets up the project from scratch. It should:

1. Check prerequisites: Python 3.11+, uv, Docker Engine running
2. Run `uv init` (if pyproject.toml doesn't exist) and `uv add` all dependencies:
   openai, pydantic, python-dotenv, docker
3. Create `.env.example` with placeholder values for LLM_API_KEY, LLM_MODEL, LLM_BASE_URL
4. Copy `.env.example` to `.env` if `.env` doesn't exist (prompt user to fill in real values)
5. Create the `src/` directory structure as specified in app_spec.txt (all __init__.py files)
6. Create the `output/` directory
7. Verify Docker connectivity: `docker info > /dev/null 2>&1`
8. Print a summary: what was set up, what the user needs to do next (fill .env, etc.)

### THIRD TASK: Start Implementation

Begin with Stage 1 (infrastructure). For each stage:
1. Implement the code
2. Run the verification steps from test_plan.json for that stage
3. Mark passing checkpoints as `"passes": true`
4. Only proceed to the next stage when all checkpoints for the current stage pass