# Battlezone Localization Tool

A premium, automated localization tool for **Battlezone 98 Redux** modders. Quickly translate bulk English text or scan your custom ODF folders to automatically collect and translate unit names into the game's `localization_table.csv`.

<img width="902" height="982" alt="image" src="https://github.com/user-attachments/assets/a97ed2b9-e43f-4524-94cf-8a669c7dc2cb" />

---

## 🎨 New Premium Aesthetics
The tool has been overhauled to match the **Battlezone Workshop Uploader** style, featuring:
* **Dark Mode**: Sleek black and neon green high-contrast UI.
* **Custom Font**: Uses the fan-made `BZONE` font by ScrapPool, provided for free use and inspired by the Battlezone visual style.
* **Tabbed Interface**: Cleanly separated tasks for manual entry and automated scanning.

---

## 🚀 Features

* **ODF Scanner (NEW)**: 
    * Point the tool at any mod folder.
    * Extracts only the player-visible `unitName` value from `.odf` files.
    * Skips ODFs without `unitName` instead of treating internal filenames or identifiers as localization text.
* **Smart De-duplication**: Automatically checks your existing CSV and skips any keys that are already present.
* **Stock-Compatible Key Generation**:
    * **ODF / Standard Names**: Preserves the exact Battlezone lookup text, e.g. `Heavy Tank` → `names:Heavy Tank`, matching the stock table instead of lowercasing/underscore-normalizing it.
    * **Mission Titles**: Detection for `.bzn` files to create `mission_title:` keys.
* **Stock Table Byte Format**: New rows are written as exactly 8 tilde-delimited fields with CRLF line endings. Western-language columns use Windows-1252 and the Russian column uses Windows-1251, matching the shipped Battlezone localization table instead of appending UTF-8 bytes to a legacy table.
* **Multi-Language Support**: ODF bulk translation defaults to a **credential-free Google HTTP backend**. It joins many unit names into each request, so a normal scan needs only a handful of HTTP calls instead of one call per name. The official **Google Cloud Translation v3** backend remains available as an optional authenticated choice. The Manual Translate tab keeps `deep-translator` as a fallback.
* **Progress Tracking**: Visual feedback during large batch translations.

---

## 🛠 Getting Started

### Option 1: Running the Executable
Download the latest platform archive from the [Releases](https://github.com/GrizzlyOne95/Battlezone98Redux_LocalizationTool/releases) page.

The executable name is intentionally stable and versionless:

- Windows: `BZLocalizationTool.exe`
- Linux/macOS: `BZLocalizationTool`

Release archives carry the version, for example `Battlezone98Redux_LocalizationTool-v2.1-windows.zip`.

### Windows application metadata

Official Windows builds use the shared **Battlezone Modding Tools** product identity:

```text
FileDescription: Battlezone Localization Tool
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZLocalizationTool.exe
```

`FileVersion` and `ProductVersion` are derived from the release tag.

### Option 2: Running from Source
1. **Clone the repo**:
   ```bash
   git clone https://github.com/GrizzlyOne95/Battlezone98Redux_LocalizationTool.git
   ```
2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the script**:
   ```bash
   python localization.py
   ```

### ODF bulk translation backends

**Free HTTP (no account)** is the default. It sends newline-delimited batches instead of making one request for every unit name. The free path now tries Google's Translate Web `MkEWBc` batchexecute RPC first, then the Google Dictionary/Chrome-extension endpoint (`clients5.google.com`), and only then the older `translate_a/single` endpoint. The tool validates that the translated result maps back to every source name before it writes anything to `localization_table.csv`.

These credential-free Google endpoints are unofficial and can change or be throttled independently. If one route is blocked, the tool automatically tries the next route. If all free routes fail, it fails closed instead of silently writing English text into translated columns. HTTP block pages are summarized in the UI rather than dumping raw HTML.

**Google Cloud v3** remains available from the backend dropdown for users who want the official authenticated service. That option requires a Google Cloud project, Cloud Translation enabled, and credentials. You can select a service-account JSON file in the app or use Application Default Credentials, and you can preconfigure `GOOGLE_CLOUD_PROJECT` / `GOOGLE_APPLICATION_CREDENTIALS`.

**Do not commit service-account JSON credentials to this repository or to a mod project.**

---

## 📂 Input Formats

### ODF Scanning
Simply use the **ODF Scanner** tab, browse to your folder, and click **Scan**. The tool handles the extraction and formatting for you.

### Manual Mode
Paste English names line-by-line.
* **Normal**: `Heavy APC` → `names:Heavy APC`
* **Missions**: `play01.bzn~The Playground` → `mission_title:play01.bzn`

### Battlezone localization table format

The tool writes the same row structure used by the stock `localization_table.csv`:

`Key~English~French~German~Spanish~Italian~Russian~Portuguese`

Each generated row contains exactly eight fields and ends with CRLF. Because the shipped table is not a single UTF-8 file, the writer encodes the key/English/French/German/Spanish/Italian/Portuguese fields as Windows-1252 and Russian as Windows-1251. Values containing the `~` delimiter or embedded line breaks are rejected rather than producing a malformed row.

---

## Code signing policy

Free code signing is provided by [SignPath.io](https://signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

### Team roles

* **Author / committer:** [GrizzlyOne95](https://github.com/GrizzlyOne95)
* **Reviewer:** GrizzlyOne95 reviews changes submitted by external contributors before merge.
* **Approver:** GrizzlyOne95 approves official release signing requests.

### Privacy

This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.

When the user explicitly runs **ODF bulk translation**, the selected source names are sent either to the credential-free Google translation HTTP endpoint (the default) or to the official Google Cloud Translation v3 API if that backend is selected. The **Manual Translate** tab uses the open-source `deep-translator` dependency. This project does not intentionally collect application telemetry or store Google Cloud credential contents.

Official Windows release binaries are built from this repository using GitHub Actions. Once SignPath Foundation signing is enabled for the project, version-tagged Windows releases are submitted from the GitHub-hosted build pipeline to SignPath for Authenticode signing and require release approval before publication.

---

## 📜 Credits
Built for the Battlezone 98 Redux modding community. Features inspired by the Workshop Uploader aesthetics.

`BZONE.ttf` was created by **ScrapPool** as a fan-made typeface inspired by the Battlezone visual style and was provided for free use. It is not presented as an extracted game font. See `THIRD_PARTY_NOTICES.md` for provenance and licensing notes.
