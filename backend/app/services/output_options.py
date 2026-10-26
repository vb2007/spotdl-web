"""The output formats and qualities this app offers (v54.2).

YouTube (and YouTube Music) serves, without Premium, Opus 251 (~130-160k VBR) and AAC 140
(~130k) at most. spotdl downloads that stream and then re-encodes it at whatever bitrate it is
told, so anything above the source only inflates the file and adds a lossy generation: a
"320k" MP3 was ~2.5x the size of what it came from, and told every player a false bitrate.
So this list holds only what the source can back:

- "best" keeps the stream as YouTube serves it (opus/m4a: no re-encode at all), or matches
  the source's bitrate for mp3, which is always a re-encode;
- the explicit bitrates are re-encode targets at or below the source.

spotdl's own --format/--bitrate choices are wider (flac/ogg/wav, 8k-320k, VBR 0-9). They're
still the ground truth for what spotdl accepts: downloads.get_supported_output_options
checks this list against them. No spotdl import here: config-time and alert-process code
can read it cheaply.
"""

BEST = "best"
FORMATS = ("opus", "m4a", "mp3")
BITRATES = (BEST, "160k", "128k", "96k", "64k")
DEFAULT_FORMAT = "opus"
DEFAULT_BITRATE = BEST


def spotdl_bitrate(format: str, bitrate: str) -> str:
    """What to hand spotdl for `bitrate`. "best" is ours, not spotdl's: "disable" makes
    spotdl move an .m4a source into place untouched and remux an Opus .webm with
    `-c:a copy` (spotdl.utils.ffmpeg); "auto" makes an mp3 at the source's own bitrate
    (spotdl falls back to 128k when yt-dlp reports none)."""
    if bitrate != BEST:
        return bitrate
    return "auto" if format == "mp3" else "disable"
