# Intel third-party foundation experiment (NOT production accepted)

This manually dispatched public runner experiment downloads only frozen public conda-forge packages, Node.js and the publicly pinned whisper.cpp revision. It creates a **public third-party foundation**, not an accepted VoiceStudio native archive. It contains no application code, model weights, profiles or private records.

## Required preparation on the owner's Windows machine

1. Copy `scripts/export_public_lock.py` into a separate temporary directory and execute it with the **private** `config/macos-intel-proof.json` as input, writing `public-intel-lock.json` into that temporary directory. Keep the private configuration file private.
2. Independently inspect `public-intel-lock.json`: it must contain only third-party package URLs, exact versions, SHA-256, sizes, public Node/Whisper pins, and optional Numba TBB hash.
3. Upload reviewed `public-intel-lock.json` alongside the three files from this ZIP to the public test repo. Do not upload any private configuration or other files. The workflow is **manual only**.
4. In Actions, choose **Public Intel third-party foundation (not production accepted)** and run on main. Only run once after review.

## Expected outputs

A GitHub Actions artifact named `public-intel-third-party-foundation-RUN_ID` contains `public-intel-foundation.tar.gz` and `public-foundation-report.json`. The tar contains `runtime/python/macos-x64` (public conda CPU stack), `runtime/node/macos-x64/bin/node`, `library/whisper/macos-x64/bin/whisper-cli`, `public-third-party-lock.json`, and embedded inventory. **No Nano inference is performed.**

## Strict scope limitations

This draft performs hash-locked input retrieval, CPU imports, architecture checks, synthetic and real-file archive round trips. It does NOT reproduce the private runtime's strict Mach-O closure, TorchAudio relocation repairs, full legal inventory, independent relocated runtime inference or private receipt. It intentionally will not satisfy `assemble-macos-intel.py` production acceptance. The native build may fail due to unsatisfied conda package dependencies, pinned URL availability, or relocation. A green CI build is foundation-only, not a shipping signal. The public archive is visible to anyone; inspect inputs before running.

**Before any production use:** run an approved private Intel relocation/closure repair and actual twice-relocated inference with the original protected inputs; generate the genuine native receipt. Do not forge a receipt or modify assembler validation.
