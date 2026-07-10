# Celesto for Pi

Run Pi's coding tools away from your laptop while keeping its interface and
conversation history local. A Celesto computer is an isolated remote computer
that holds your project and runs the tools. Model credentials are the secrets
Pi uses to access an AI model. They stay on your machine.

Read the [complete Pi cloud setup guide](https://docs.celesto.ai/celesto-sdk/guides/pi-coding-agent) for synchronization, security, lifecycle, and troubleshooting details.

## Quickstart

Before starting, install [Pi](https://github.com/earendil-works/pi) and
configure it with a model provider. You also need Node.js 22.19 or newer and a
Celesto API key.

Install the extension:

```bash
pi install npm:@celestoai/pi
```

Set your Celesto API key:

```bash
export CELESTO_API_KEY="your-celesto-api-key"
```

From the project you want to work on, start Pi:

```bash
pi --celesto
```

The extension creates a Celesto computer, copies the project to `/workspace`, and runs Pi's `read`, `write`, `edit`, and `bash` tools there.

## Copy changes back

The Celesto workspace is the active copy while Pi is running. Copy changes between it and your local project explicitly:

```text
/celesto sync
```

The sync command preserves independently changed files under `.celesto-conflicts/` instead of overwriting local work.

## Check the computer

```text
/celesto status
```

This shows the computer name, workspace, cleanup behavior, and current sync revision.

## Keep the computer

Computers created by the extension are deleted only after a successful final sync. Keep one for later use with:

```text
/celesto keep
```

The command prints the exact `celesto computer delete` command to use when you no longer need it.

## Reuse an existing computer

Get a computer name from `celesto computer create` or `celesto computer list`, then pass it to Pi:

```bash
pi --celesto --celesto-computer curie
```

The extension never deletes a computer selected by the caller. If `/workspace` already contains files, those files remain authoritative until you run `/celesto sync`.

## Files that are not copied

The extension reads `.gitignore` and then applies `.celestoignore` overrides. It also excludes common secrets, dependency directories, build output, files larger than 25 MB, and symbolic links. `.git` remains available so Pi can inspect branches and diffs.

Add project-specific patterns to `.celestoignore`:

```gitignore
fixtures/private/
*.large-test-data
```

Model-provider credentials are never copied into the Celesto computer. `CELESTO_API_KEY` is used only by the local SDK to contact Celesto.

## Current scope

This first version uses compressed archives and base64 file transfer. It intentionally does not override Pi's `grep`, `find`, or `ls` tools yet. Native workspace transfer and automatic synchronization require future Celesto backend support.
