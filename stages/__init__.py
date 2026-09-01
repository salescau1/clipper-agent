"""Pipeline stages.

Stage modules are imported lazily by the caller so optional dependencies
such as WhisperX remain isolated in their dedicated environment.
"""

__all__ = [
    "stage1_curate",
    "stage2_download",
    "stage3_render",
    "stage4_subtitles",
]