# Prepare a radio voice line

Start with a clean recording such as `line01.wav` in a separate recording folder. The Audio page processes the file; it does not record your microphone or add a mission event.

## Process one recording

1. Open **Assets → Audio**.
2. Under **INPUT SOURCE**, select **SINGLE FILE**.
3. Set **WAV PROFILE** to **Radio VO (22050Hz)**.
4. Set **INTENSITY** to **light** for a first pass.
5. Leave **ENABLE PHASER** and **ENABLE ECHO** off initially.
6. Choose a **SQUELCH TONE**. Use **commbeep.wav (Radio/Orders)** for this example, or **None** for no beep.
7. Click **INITIATE WAV PROCESSING**. The file picker opens at this point; select your recording.
8. Wait for completion and read **HUD LOG**. Check that your file was exported; do not rely only on the completion popup.

The output is written beside the recording folder's source file, inside a new subfolder:

```text
Recording/
  line01.wav
  bz98_radio_export/
    line01.wav
```

The Radio VO profile writes **mono, 22050 Hz, unsigned 8-bit PCM WAV**. Reprocessing the same source name writes the same output path, so save versions you want to keep.

## Listen and make a timing list

Listen to the exported WAV in an audio player. Check speech clarity, clipping, silence and the beep level. Increase the intensity or add effects only after checking the first result.

For a timing list, click **EXPORT TIMING MANIFEST (CSV)**, choose `bz98_radio_export`, then choose where to save the CSV. It lists **Filename**, **Duration** and **Type**. Its duration includes processing and any added beeps.

## Use the sound in your mod

Copy the exported `line01.wav` into the working mod. Something must reference it before the game will play it.

For a simple unit-response test, use the complete `avtank.odf` working copy from [Make a tougher tank](Change-a-unit). In its `[CraftClass]` section, replace the existing selection-response entry with:

```ini
selectWaitMsg = "line01.wav"
```

Save, validate and deploy the ODF and WAV. Select an idle tank in game to check the response. Restore the original entry after the test if this is not the behavior you want. Mission-event playback needs a reference in your mission logic; the Audio page does not insert one.

The processing and CSV export were checked with test audio. Listen to your own recording and test its game trigger separately.

[Home](Home) · [Publish a Workshop item](Publish-a-Workshop-item)
