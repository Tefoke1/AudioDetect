# Release checks

1. Build from the public source tree, using the pinned dependencies and a fresh output directory.
2. Run Python and Android tests. Exercise both languages, file filters, cached searches, Stop, playback and exports. Test bundled executables without relying on the development Python environments.
3. Include only source, documented build inputs, licenses and intended binaries. Never copy working databases, recordings, transcripts, reports, settings, logs, local properties, caches or signing credentials into a release.
4. Run `python tools/audit_public.py`. Review its findings and the Git staged-file list. Check compiled Python code filenames and archived payloads as well as ordinary source files. Use an additional private denylist for local names and paths; never publish that denylist.
5. Verify APK permissions and signatures. Preserve third-party notices. Generate SHA-256 sums for final archives after signing.
6. Tag the exact source used for the binaries, publish the source and binaries together, and record the actual checks and any untested platforms in the release notes.

Git ignores are a convenience, not a privacy boundary. A release uses an explicit file list and a clean history. User-provided issue reports can contain private material; request a synthetic reproduction instead of a call recording.
