> **Toolbox note:** this is the standalone tool's README, kept for reference.
> In the toolbox the Audio page needs no FFmpeg: decoding and encoding use
> soundfile (libsndfile) and the radio effects are NumPy/SciPy
> (`bztoolbox/modules/audio/processing.py`). Inputs: WAV, MP3, OGG, FLAC, AIFF
> (M4A/AAC is no longer accepted).

# Battlezone Audio Tool

**Battlezone Audio Tool** (formerly **BZRadio**) is a specialized utility designed for the **Battlezone 98 Redux** modding community. It streamlines the process of mastering audio for the legacy engine, handling the strict formatting requirements for both unit voiceovers (VO) and mission soundtracks.

## Features

- **Radio VO Mastering:** Automatically applies high-pass/low-pass filtering, compression, and tremolo to simulate authentic analog radio transmissions. Can be disabled.
- **Intro/Outro Beeps:** Automatically appends "squelch" tones to the start and end of transmissions. Supports `commbeep.wav` (orders), `unitbeep.wav` (responses), or custom user files. Can be disabled.
- **WAV Profiles:** Supports both **Radio VO** export (`22050Hz` mono `PCM_U8`) and a dedicated **Thrust/Turbo Loop** export path (`11025Hz` mono `PCM_U8`, plain RIFF/WAVE).
- **Music Soundtrack Path:** Converts audio to high-fidelity **Stereo OGG** (44100Hz) without radio distortion, perfect for background music.
- **Metadata:** Can strip and remove all meta data and non-audio streams.
- **Lua Timing Manifest:** Exports a CSV of file durations—essential for scripters to perfectly time subtitles and mission events in Lua.
- **Batch & Single Mode:** Process an entire folder of source files or a single specific track with one click.

<img width="802" height="982" alt="image" src="https://github.com/user-attachments/assets/c1df73d5-a945-446c-8e8e-59c8cd4728f0" />

---

## Audio Specifications

| Target Type | Format | Sample Rate | Channels | Effects Applied |
| :--- | :--- | :--- | :--- | :--- |
| **Radio/Unit VO** | WAV (PCM_U8) | 22050 Hz | Mono | Bandpass, Tremolo, Beeps |
| **Thrust/Turbo Loops** | WAV (PCM_U8) | 11025 Hz | Mono | None, plain RIFF/WAVE rewrite |
| **Soundtrack** | OGG (Vorbis) | 44100 Hz | Stereo | None (Clean / Full Range) |

---

## Installation & Usage

### For Users (Standalone EXE)
1. Download the latest Windows release archive from the [Releases](../../releases) tab.
2. Extract and launch `BZAudioTool.exe`.
3. **WAV Path:** Use for unit voices and radio chatter (includes beeps and radio filters).
4. **OGG Path:** Use for mission music (full quality, no filters).

The executable name is intentionally stable across releases. Release archives carry the version number, while Windows file metadata reports the application and product version.

### Windows application metadata

Release builds use the shared Battlezone modding-tool suite convention:

```text
FileDescription: Battlezone Audio Tool
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZAudioTool.exe
```

### For Developers (Running from Source)
If you wish to run the script or build it yourself:

1. **Requirements:** Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Install FFmpeg or place `ffmpeg.exe` where the tool can access it.
3. Run:
   ```bash
   python audio.py
   ```
4. To generate the Windows executable using the same naming and metadata convention as release builds:
   ```powershell
   python scripts/generate_app_icon.py branding/repo_icon.svg branding/app_icon.ico --png branding/app_icon.png
   python scripts/generate_version_info.py --version (Get-Content VERSION).Trim() --output branding/version_info.txt
   pyinstaller audio.py --name BZAudioTool --onefile --windowed --icon "branding/app_icon.ico" --version-file "branding/version_info.txt" --add-data "branding/app_icon.ico:branding" --add-data "branding/app_icon.png:branding" --add-data "BZONE.ttf:." --add-data "commbeep.wav:." --add-data "unitbeep.wav:." --add-data "LICENSE:." --runtime-hook branding/pyinstaller_icon_hook.py
   ```

## Credits & Licensing

Code: Licensed under the MIT License.

FFmpeg: FFmpeg is licensed under the LGPLv2.1 where applicable to the distributed build.

Battlezone 98 Redux Assets: Default beep files (`commbeep.wav`, `unitbeep.wav`) are the property of Rebellion / Activision and are included for non-commercial fan-use specifically for the BZ98 modding community.
