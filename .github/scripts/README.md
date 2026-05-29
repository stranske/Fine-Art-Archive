# GitHub Scripts

This directory contains scripts used by GitHub Actions workflows for agent automation.

## JavaScript Scripts

| Script | Purpose |
|--------|---------|
| `issue_pr_locator.js` | Locates related PRs for issues |
| `issue_context_utils.js` | Context gathering utilities |
| `issue_scope_parser.js` | Parses issue scope from body text |
| `keepalive_instruction_template.js` | Generates keepalive instruction comments |

## Python Scripts

| Script | Purpose |
|--------|---------|
| `decode_raw_input.py` | Decodes base64 input for issue intake |
| `parse_chatgpt_topics.py` | Parses Issues.txt format |
| `fallback_split.py` | Fallback splitter for issue parsing |

## Usage

These scripts are called by the reusable workflows in stranske/Workflows. They should be synced from the Workflows repo to ensure compatibility.

To sync scripts:
```bash
# Fetch latest from Workflows repo
for script in issue_pr_locator.js issue_context_utils.js issue_scope_parser.js keepalive_instruction_template.js; do
  curl -sL "https://raw.githubusercontent.com/stranske/Workflows/main/.github/scripts/$script" -o ".github/scripts/$script"
done
```
