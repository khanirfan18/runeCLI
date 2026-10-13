# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-10-13

### Fixed
- Removed hardcoded test hooks and "not wired yet" placeholders from production CLI commands.
- Fixed unhandled crash when config.json is empty or corrupt; Rune now warns to stderr and prompts for credentials again.
- Prevented test suites from launching real external IDE processes by adding an autouse fixture in conftest.
- Added clean non-interactive terminal requirement error when running without a TTY.

### Added
- Added `--version` and `-V` command line options displaying package version.
- Added GitHub Actions multi-platform CI workflow for Linux, macOS, and Windows.

### Security
- Hardened filesystem permissions: `~/.rune` created as 0700, initial `config.json` as 0600, and temporary files set to 0600 before atomic rename.

### Changed
- Configured sdist build targets to include documentation and tests while excluding .gitignore and build caches.
- Updated README documentation to match CLI difficulty names, startup sequence, and platform status.
- Bumped version to 0.1.3.

## [0.1.2] - 2026-10-05

### Fixed
- Handled harmless Gemma OK reason explanations in model output parsing.

### Changed
- Bumped version to 0.1.2.

## [0.1.1] - 2026-10-05

### Changed
- Prepared RuneCLI package distribution and packaging clean-up fixes for PyPI release.

## [0.0.1] - 2026-10-04

### Added
- Initial release of RuneCLI foundation, theme, quest discovery pipeline, and documentation.
