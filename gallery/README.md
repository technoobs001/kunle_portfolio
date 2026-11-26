# Gallery: how to add photographs

## The 3-step workflow

1. Drop new photographs into `gallery/images/` (jpg, png, webp, avif, gif, bmp, tif).
2. Run the script from the `gallery/` folder:

   ```
   python process_images.py
   ```
3. Refresh the Archive page. That's it: no HTML, CSS or JavaScript to edit.

The script only does work that is needed. Photos that haven't changed are skipped
(a re-run with nothing new takes under a second).

**Requirements:** Python 3.9+ and `pip install pillow numpy` (SciPy is optional, it just speeds things up).

## What the script does for each photo

| Step | Detail |
|---|---|
| Orientation | portrait / landscape / square from the pixel size (EXIF rotation respected) |
| Frame | picks a frame whose *window* shape suits the photo. Frames are analysed automatically (the transparent opening is detected), so names like `portrait-frame-03.png` don't matter |
| Variety | frames and stickers are chosen at random but **balanced**: the least-used ones are favoured, and the same frame is never used twice in a row when there is another choice |
| Fit | the photo is scaled to *cover* the window (no stretching), clipped to the window shape (ovals included) and tucked under the frame edge |
| Overlay | a soft light overlay (12 % warm white) sits above the photo and below the frame and stickers |
| Stickers | At most **one** sticker per frame (about a third of frames get none). It rests on the frame itself, mostly inside its outline and away from the photograph. Stickers are baked into the image, so they never drift when a frame is rotated or moved on the page |
| Shadow | a soft drop shadow is baked in |
| Output | WebP and AVIF at several widths in `generated/`, named with a content hash |
| Manifest | `manifest.json` (and `manifest.js`, a copy for opening the page from disk) |

Choices are saved in the manifest, so **existing photos keep their frame, stickers and position** when you add more.

**The ivy vine** (`stickers/sticker-10-vine.png`) is a *hanging* sticker: instead of sitting on the rim it drapes down from the top edge of the picture inside the frame, like the design reference, and counts as that frame's one sticker. It is used sparingly. Any sticker whose file name contains `vine` or `ivy` behaves this way.

## The design layout (`design.json`)

`design.json` pins photographs to the exact frame, sticker, crop and page position used in the design layouts (desktop and mobile share one artboard). `process_images.py` reads it: photographs listed in it always get exactly that look and position; every other photograph is handled at random, as described above, and is placed below the designed block. `DESIGN_MAPPING.md` lists the full photo-to-frame table.

* To pin another photograph, copy an existing entry in `design.json`, change the file name, frame and `frame_box`, and run the script. To release a pin, delete its entry.
* A painting that must appear in two frames needs two files; mark the copy with `"allow_duplicate": true`.
* iPhone `.heic` photos are read directly if you run `pip install pillow-heif` once (otherwise the script tells you which files it skipped).

## Viewing a painting full size

Clicking (or tapping, or pressing Enter on) any framed painting opens it in a frosted full-screen viewer with **previous / next** buttons, a **close** button and a counter. Also: left/right arrow keys, Esc to close, swipe on touch screens, click on the veil to close. The viewer uses the largest generated size and needs no setup, so new photos get it automatically.

## Everyday options

```
python process_images.py --dry-run       # show what would happen, change nothing
python process_images.py --reshuffle     # pick new frames/stickers for every photo
python process_images.py --seed 42       # reproducible choices for NEW photos
python process_images.py --force         # re-render everything
python process_images.py --no-avif       # WebP only (faster)
```

Optional captions: create `images/captions.json`

```json
{ "my-painting.jpg": { "alt": "Oil painting of a woman in a field", "title": "Field, 2024" } }
```

## Adding frames or stickers

* **New frame:** drop a PNG (transparent window, frame art around it) into `frames/`. It is detected and used automatically. Frames whose window shape is closer to a photo's shape are preferred, so a new *square* frame will start receiving square photos.
* **New sticker:** drop a transparent PNG into `stickers/`.
* Anything unreadable, or a frame without a closed window, is reported and skipped.

## Tuning the look

The settings are at the top of `process_images.py`: overlay colour/opacity, shadow, WebP/AVIF quality, maximum width, how large stickers are, and how close to the photo they may sit.

## Performance and caching

* Every generated file has a content hash in its name, so it can be cached for a year (`immutable`). Edit a photo and the name changes, so visitors always get the new version.
* `manifest.json` is served with `no-cache`: browsers re-check it (a tiny 304 response) so new photos appear straight away.
* The page uses `<picture>` with AVIF/WebP, `srcset` + `sizes` (phones download the small files), `loading="lazy"`, and explicit width/height (no layout shift). The hero art is preloaded.
* Ready-made header rules are in the site root: `_headers` (Netlify / Cloudflare Pages), `.htaccess` (Apache) and `nginx.example.conf`.
* For local viewing run `python serve.py` in the site root and open http://localhost:8000/gallery.html. It applies the same caching rules.

## Folder map

```
gallery/
  images/         <- your photographs go here
  frames/         frame artwork (transparent window)
  stickers/       sticker artwork
  generated/      framed, optimised output (do not edit; safe to delete, it is rebuilt)
  manifest.json   what the website reads
  manifest.js     same data, for opening gallery.html straight from disk
  process_images.py
```
