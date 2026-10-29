# Private images (Cisco IOS and other licensed images)

VASYA GNS LAB never ships, mirrors or downloads licensed vendor images from a public location.
If you own licensed copies, keep them in a **private source**. VASYA then fetches them
automatically during installation (or `vasya fetch`), checks each file against your private
manifest, and adds the devices. Without a private source those devices are shown as
"image not available"; the installation still finishes.

## What a private source contains

1. `vasya-private-manifest.json`: describes the devices and pins every file by SHA-256 and size.
2. The image files, named by their file name (for example `c7200-p-mz.123-19.image`) or by their SHA-256.

Manifest format (format 1):

```json
{"format": 1,
 "blocks": [{"block_id": "cisco-ios-c7200-p-mz-123-19", "name": "Cisco IOS c7200-p-mz.123-19",
             "vendor": "Cisco", "category": "router", "runtime": "dynamips", "architecture": "c7200",
             "ram": 512,
             "images": [{"logical_filename": "c7200-p-mz.123-19.image",
                         "sha256": "<64 hex>", "size": 42887964, "disk_slot": "image"}],
             "appliance": {"...": "GNS3 appliance JSON for this device"}}]}
```

A file whose SHA-256 or size differs from the manifest is rejected.

## Where to put it (pick one)

**A. A folder on the same computer (simplest).**
Put the manifest and the image files in `~/VASYA-GNS-LAB/Images/`
(Windows: `%USERPROFILE%\VASYA-GNS-LAB\Images\`). This folder is checked by default.

**B. A private GitHub release (works on every computer where you are signed in to `gh`).**

```sh
gh repo create vasya-gns-lab-private --private
gh release create images --repo <your-login>/vasya-gns-lab-private --title images --notes "private images" \
    vasya-private-manifest.json c7200-p-mz.123-19.image ...
```

With the GitHub CLI signed in (`gh auth login`), VASYA checks
`<your-login>/vasya-gns-lab-private`, release `images`, by default. Keep this repository private.

**C. A private HTTPS location.** Any web server or object store that serves
`<base URL>/vasya-private-manifest.json` and `<base URL>/<file name>`. If it needs a token,
put the token in the environment variable `VASYA_PRIVATE_TOKEN` (sent as `Authorization: Bearer`).
Tokens are never written to logs or reports.

## Choosing sources explicitly

Sources are tried in order; the first one that has a file wins.

* Environment variable `VASYA_PRIVATE_SOURCES`, `;`-separated, for example
  `VASYA_PRIVATE_SOURCES="~/VASYA-GNS-LAB/Images;gh:me/vasya-gns-lab-private@images;https://files.example.org/vasya/"`.
  `VASYA_PRIVATE_SOURCES=none` turns private sources off.
* Otherwise the file `~/.config/vasya-gns-lab/private-sources.json`
  (Windows: `%APPDATA%\vasya-gns-lab\private-sources.json`, or the path in `VASYA_PRIVATE_SOURCES_FILE`):

```json
{"sources": [{"type": "dir", "path": "~/VASYA-GNS-LAB/Images"},
             {"type": "github-release", "repo": "me/vasya-gns-lab-private", "tag": "images"},
             {"type": "https", "url": "https://files.example.org/vasya/", "token_env": "VASYA_PRIVATE_TOKEN"}]}
```

* Otherwise the defaults from options A and B.

## Checking

```sh
vasya fetch --dry-run          # lists missing images and whether each comes from the lock or a private source
vasya fetch                    # downloads public and private images and helper programs
```

Fetched images are stored in `VASYA-GNS-LAB/Store/user/sha256/`, named by their SHA-256.

## Offline installation

A private offline bundle (`build_bundle.py --profile private`, see BUILD.md) contains every image
and needs no network. It is for your own machines only: never publish it.
