# CLAUDE.md

This file provides guidance for AI assistants (Claude and others) working in this repository.

## Repository Overview

This is a freshly initialized Git repository (`yanyaoxiao/aitest`). No source code, framework, or tooling has been committed yet. This CLAUDE.md will be updated as the project evolves.

## Current State

- **Branch**: `claude/add-claude-documentation-hWFru`
- **Commits**: None yet (initial repository)
- **Tech stack**: Not yet defined
- **Dependencies**: None yet

## Git Conventions

### Branch Naming

- Feature branches: `feature/<short-description>`
- Bug fixes: `fix/<short-description>`
- Claude-initiated branches: `claude/<description>-<session-id>`
- Never push directly to `main` or `master` without a pull request

### Commit Messages

Use the imperative mood and keep the subject line under 72 characters:

```
Add user authentication module
Fix null pointer dereference in parser
Update dependencies to latest stable versions
```

For larger changes, add a body separated by a blank line:

```
Refactor database connection pooling

Replace the single-connection model with a connection pool to improve
throughput under concurrent load. Pool size is configurable via
the DATABASE_POOL_SIZE environment variable.
```

### Pull Requests

- Keep PRs focused and small when possible
- Include a summary of what changed and why
- Link to any relevant issues

## Development Workflow

Since no tooling is defined yet, the general workflow is:

1. Create a branch from `main`
2. Make changes with clear, atomic commits
3. Push the branch and open a pull request
4. Address review feedback
5. Merge after approval

## Code Quality Guidelines

These apply regardless of the eventual tech stack:

- **Clarity over cleverness**: Write code that is easy to read and understand
- **Minimal changes**: Only modify what is necessary for the task at hand
- **No dead code**: Remove unused variables, imports, functions, and files
- **No premature abstraction**: Don't generalize until there are at least two concrete use cases
- **Security first**: Never commit secrets, credentials, or API keys; validate all external input
- **Test what matters**: Write tests for logic that could break silently

## For AI Assistants

### Before Making Changes

1. Read the files you intend to modify — do not guess at their content
2. Understand the existing patterns before introducing new ones
3. Check whether a relevant utility or helper already exists

### When Implementing Features

- Keep solutions simple and focused on the stated requirement
- Do not add error handling, logging, or fallbacks for scenarios that cannot occur
- Do not add configuration knobs, feature flags, or backwards-compatibility shims unless asked
- Do not create new files if an existing file is the right place for the change

### When This File Should Be Updated

Update CLAUDE.md whenever:
- A tech stack or framework is chosen
- Build, test, or lint commands are established
- Architectural decisions or conventions are agreed upon
- New development workflows are introduced

## Updating This File

As the project is built out, add sections for:

```
## Tech Stack
## Project Structure
## Build & Run
## Testing
## Linting & Formatting
## Environment Variables
## Deployment
```
