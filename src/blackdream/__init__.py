"""BlackDream: cross-platform OpenCore EFI builder."""

#: PEP 440 version, the one that goes into package metadata and the window's
#: version resource. ``RELEASE_LABEL`` is what a human reads.
__version__ = "0.9.0b6"

#: What the window, the CLI and the environment report display.
RELEASE_LABEL = "0.9.0-beta.6"

#: This build is pre-release: it asks for reports, it does not promise coverage.
PRERELEASE = True

__all__ = ["core", "ui", "__version__", "RELEASE_LABEL", "PRERELEASE"]
