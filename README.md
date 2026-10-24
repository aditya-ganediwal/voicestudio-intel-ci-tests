# Intel archive contract — public synthetic tests

This repository tests generic `.tar.gz` packaging behavior on an **actual Intel macOS 15 GitHub-hosted runner**. It does not contain, import, download, or execute VoiceStudio production code, models, or runtime archives.

## Scope

- Independent synthetic files resembling executable, library, license, and nested-tree layout
- SHA-256 and byte-size checks; POSIX executable mode preservation
- Canonical path-string sorting, comparison regardless of list order, duplicate and unsafe-path rejection
- Hash, size, mode mismatch diagnostics; archives with altered outer digest are rejected
- No network runtime dependencies, third-party Python packages, or uploaded artifacts

## Run manually

Open **Actions → Intel synthetic archive contract → Run workflow → main → Run workflow**. The job uses `macos-15-intel` and will be marked green or red. Inspect **Run synthetic archive contract tests** for individual test names.

## Local

Run `python3 -B tests/test_archive_contract.py -v` with Python 3.11+.

## Explicit limits

Passing this harness proves only the independent synthetic archive contract on the indicated host, **not** byte-for-byte production compatibility, actual Nano inference, native linker closure, or the customer package. Never add private files, tokens, internal URLs, model weights, or runtime artifact downloads to this public repository.
