# Battlezone ZFS Specialist

A high-performance archive explorer and packer for Battlezone (1998) `.zfs` files. This tool allows modders to browse, search, extract, force-extract encrypted ZFS archives, and create encrypted/compressed archives compatible with the BZ1 engine.

## Features
* **Full Explorer:** Browse archive contents without extracting first.
* **Instant Search:** Filter thousands of files by name or extension in real-time.
* **Smart Packing:** Build new ZFS archives with LZO1X-1 compression.
* **XOR Crypto:** MakeZFS-compatible encrypted archive extraction.
* **Legacy Header Support:** Opens both `ZFSF` archives and legacy `LZO205BZEF\\xFF\\xFF` MakeZFS/LZO archives.
* **Portable:** Standalone EXE (no Python installation required).

<img width="1002" height="732" alt="image" src="https://github.com/user-attachments/assets/e5d33deb-7d5d-470f-a7ed-1255d609caac" />

## Installation & Usage
1. Download the latest Windows release archive from the Releases tab.
2. Extract and launch `BZZFSSpecialist.exe`.
3. **To Extract:** Open a ZFS, select files (multi-select supported), and click Extract.
4. **Manual Key Input (optional):** You can enter a decimal key, hex key (for example `0xCBA07D86`), or a password string. Passwords are converted using CRC32 to match MakeZFS behavior.
5. **Encrypted Archives:** For encrypted/compressed files, data is decompressed first and then XOR-decoded with the 32-bit key stream.
6. **To Pack:** Go to the Packer tab, select a folder of files, set your XOR key, and build.

The executable name is intentionally stable and versionless. Release archives carry the version, for example `Battlezone98Redux_ZFSSpecialist-v3.1.3-windows.zip`.

### Windows application metadata

Release builds follow the shared Battlezone Modding Tools convention:

```text
FileDescription: Battlezone ZFS Specialist
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZZFSSpecialist.exe
```

`FileVersion` and `ProductVersion` are generated from the Git release tag.

### Building locally

A normal local PyInstaller build remains valid:

```powershell
python -m PyInstaller --noconfirm --clean ZFSSpecialist.spec
```

To include the same Windows version metadata used by release builds, generate the version-info file first:

```powershell
python scripts/generate_version_info.py --version "v$((Get-Content VERSION).Trim())" --output branding/version_info.txt
python -m PyInstaller --noconfirm --clean ZFSSpecialist.spec
```

The resulting executable is `dist/BZZFSSpecialist.exe`.

## Repository Structure
* `/src`: Python source code for the GUI and logic.
* `/dll_source`: C++ source code for the LZO bridge DLL.
* `/lib`: Original LZO library headers and references.
* `zfs.ico`: Custom application icon.

## Credits & Acknowledgments
* **GrizzlyOne95**: Developer.
* **Blake**: Inspiration and original logic from the `UnZFS` project.
* **Markus F.X.J. Oberhumer**: Author of the [LZO Real-Time Data Compression Library](http://www.oberhumer.com/opensource/lzo/).
* **The BZ1 Community**: For keeping the 1998 classic alive.

## License
This project is licensed under the **GNU General Public License v2.0 (GPL-2.0)**.
As this tool utilizes the LZO library (GPL), the source code for this tool and its bridge are provided freely to remain compliant with LZO's licensing terms.

## Disclaimer
This tool is provided "as-is" without warranty of any kind. It is a fan-made project and is not affiliated with Activision or Rebellion.
