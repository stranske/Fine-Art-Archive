# Template

A template Python repository with [stranske/Workflows](https://github.com/stranske/Workflows) CI integration and CLI Codex agent automation.

## Features

- 🐍 **Python 3.11+** - Modern Python with type hints
- 🔧 **Ruff** - Fast Python linting and formatting
- 🔍 **MyPy** - Strict type checking
- 🧪 **Pytest** - Testing with 80% coverage requirement
- 🤖 **CLI Codex Automation** - Gate-triggered keepalive for automated development
- 🔄 **Dual Checkout Pattern** - Consumer repo + centralized Workflows scripts

## Quick Start

```bash
# Clone the repository
git clone https://github.com/stranske/Template.git
cd Template

# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check src/ tests/

# Run type checking
mypy src/ tests/
```

## Project Structure

```
Template/
├── .github/
│   ├── codex/
│   │   ├── AGENT_INSTRUCTIONS.md  # Codex agent guidelines
│   │   └── prompts/               # Task execution templates
│   ├── scripts/                   # Agent automation scripts (dual checkout from Workflows)
│   └── workflows/                 # GitHub Actions workflows
├── docs/                          # Documentation
├── src/
│   └── my_project/                # Main package
├── tests/                         # Test suite
├── Issues.txt                     # Agent issue queue
├── pyproject.toml                 # Project configuration
└── README.md
```

## Workflows

This repository uses reusable workflows from [stranske/Workflows](https://github.com/stranske/Workflows):

### Core CI & Quality

| Workflow | Purpose | Trigger |
|----------|---------|---------|
| **Gate** | PR validation (CI, lint, tests) | Pull request |
| **CI** | Push-to-main continuous integration | Push to main |
| **Autofix** | Automatic lint/format fixes | Label: `autofix` |

### Agent Workflows (CLI Codex)

| Workflow | Purpose | Trigger |
|----------|---------|---------|
| **Keepalive Loop** | Runs Codex CLI after Gate passes | Gate completion, PR label |
| **PR Meta** | Updates PR status summaries | PR events |
| **Issue Intake** | Creates PRs from labeled issues | Issue labeled |
| **Guard** | Security checks for agent execution | Before agent runs |
| **Bot Comment Handler** | Processes @codex commands | Issue comments |
| **Autofix Loop** | Autofix integration with keepalive | Autofix + agent label |

**Note:** `agents-orchestrator.yml` is legacy and can be removed. The current architecture uses `agents-keepalive-loop.yml` which integrates with the Gate workflow for event-driven triggering.

## Agent Automation

This template uses the **Gate-triggered keepalive** architecture:

### How It Works

1. **Create Issue** with structured Scope/Tasks/Acceptance sections
2. **Label Issue** with `agent:codex`
3. **Issue Intake** creates PR from issue
4. **Gate Workflow** runs CI validation
5. **Keepalive Loop** triggers after Gate completion
   - Evaluates eligibility (unchecked tasks, no pause labels)
   - Runs CLI Codex via `reusable-codex-run.yml`
   - Codex implements changes and pushes commits
6. **Gate Runs Again** → loop continues
7. **Completion** when all acceptance criteria checked

### Key Components

- **Activation**: PR must have `agent:codex` label, Gate success, unchecked tasks
- **Task Tracking**: Agent updates checkboxes in PR body after completing work
- **Progress Detection**: Automatic checkbox reconciliation via session analysis
- **Failure Handling**: After 3 failures, adds `needs-human` label and pauses
- **Concurrency**: One keepalive run per PR (configurable via `agents:max-parallel:N`)

### Control Labels

| Label | Effect |
|-------|--------|
| `agent:codex` | Enables Codex automation |
| `agents:pause` | Halts all agent activity |
| `needs-human` | Auto-added after failures, blocks keepalive |
| `agents:max-parallel:N` | Override concurrent run limit (default: 1) |

### Using Issues.txt

Add issues to `Issues.txt` using the structured format, then trigger the intake workflow:

```
1) Issue title here
Labels: agent:codex, enhancement

## Scope
Explanation of what needs to be done and why.

## Tasks
- [ ] Task 1
- [ ] Task 2
- [ ] Task 3

## Acceptance Criteria
- [ ] All tests pass
- [ ] Code is documented
- [ ] Coverage ≥80%

Implementation notes
- Technical details or constraints
```

## Setup for New Repos

### Required Secrets

| Secret | Purpose | Alternative |
|--------|---------|-------------|
| `CODEX_AUTH_JSON` | ChatGPT auth for Codex CLI | Recommended |
| `WORKFLOWS_APP_ID` | GitHub App ID | Use with APP_PRIVATE_KEY |
| `WORKFLOWS_APP_PRIVATE_KEY` | GitHub App private key | Use with APP_ID |
| `SERVICE_BOT_PAT` | Bot PAT for automation | Required |
| `OWNER_PR_PAT` | Owner PAT for PR operations | Optional |

**Note:** Choose either `CODEX_AUTH_JSON` OR the GitHub App credentials, not both.

### Required Environments

Create in **Settings** → **Environments**:
- `agent-standard` - For standard agent execution

### Repository Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ALLOWED_KEEPALIVE_LOGINS` | Users who can trigger keepalive | `stranske` |

### Branch Protection

Configure branch protection for `main`:
- Require status checks: `Gate / gate`
- Require pull request reviews: 1 approval
- Dismiss stale reviews on new commits

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run all checks
ruff check src/ tests/
mypy src/ tests/
pytest --cov

# Format code
ruff format src/ tests/
```

## Troubleshooting

### Keepalive Not Triggering

- Verify PR has `agent:codex` label
- Check Gate workflow passed
- Ensure PR body has unchecked tasks
- Look for `agents:pause` or `needs-human` labels
- Review keepalive summary comment for skip reasons

### No Automated Status Summary

- Verify issue has Scope/Tasks/Acceptance sections
- Run `agents-pr-meta.yml` manually
- Check PR links to source issue

### Agent Failures

After 3 failures, keepalive pauses and adds `needs-human`:
1. Review failure reason in keepalive summary
2. Fix the issue (code, prompt, auth)
3. Remove `needs-human` label to resume

### Permission Errors

- Verify `CODEX_AUTH_JSON` or GitHub App credentials are set
- Check environment `agent-standard` exists
- Ensure PATs have required scopes: `repo`, `workflow`

## Documentation

- [Workflows Repo](https://github.com/stranske/Workflows) - Central workflow library
- [Consumer README](https://github.com/stranske/Workflows/blob/main/templates/consumer-repo/README.md) - Complete setup guide
- [Keepalive Architecture](https://github.com/stranske/Workflows/blob/main/docs/keepalive/GoalsAndPlumbing.md) - Detailed design
- [Setup Checklist](docs/keepalive/SETUP_CHECKLIST.md) - Step-by-step configuration

## License

MIT License - see [LICENSE](LICENSE) for details.
