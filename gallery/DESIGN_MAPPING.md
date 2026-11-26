# Design mapping: which photograph sits in which frame

Generated from `manifest.json` and `design.json`. The desktop and mobile layouts are the same artboard (1440 units wide), so one mapping covers both.

## A. Photographs taken from the design layouts

Pinned: each has the exact frame, sticker, crop and position of the design. Reading order (top to bottom, left to right). Positions are of the frame canvas on the 1440-wide artboard.

| # | Photograph file | Painting | Frame | Sticker | Position (x, y, width) |
|---|---|---|---|---|---|
| 1 | `IMG_3170.jpg` | Oil portrait of a smiling man with glasses wearing a white shirt and kente cloth | `portrait-frame-01` | 07-paper-pink-flower | 21, 1335, 667 |
| 2 | `IMG_1257.JPG` | Oil portrait of a woman in a dark dress and pearl necklace against a red halo | `portrait-frame-01` | 02-clover | 721, 1379, 302 |
| 3 | `IMG_1283.JPG` | Green-toned painting of a man smoking a cigarette in the dark | `portrait-frame-02` | 08-paper-rose | 1058, 1391, 338 |
| 4 | `IMG_1260.JPG` | Painting of a woman with long beaded braids seen from behind in a golden field | `landscape-frame-02` | none | 741, 1852, 634 |
| 5 | `IMG_1285.JPG` | Portrait of a young man with short locs in a blue hoodie | `portrait-frame-03` | none | 532, 2295, 307 |
| 6 | `IMG_2490.jpg` | Painting of a woman in a green and keffiyeh-patterned top with white doves and a crowd behind her | `landscape-frame-01` | 04-gold-sun | 76, 2338, 420 |
| 7 | `IMG_1255.JPG` | Portrait of a girl with puffs, a red bow and a fur collar | `portrait-frame-04` | none | 836, 2330, 594 |
| 8 | `IMG_1254.JPG` | Portrait of a woman with short natural hair and a ruffled white collar | `portrait-frame-05` | 01-chain | 23, 2680, 447 |
| 9 | `IMG_1257-design-copy.JPG` | Oil portrait of a woman in a dark dress and pearl necklace against a red halo | `portrait-frame-01` | 09-rome-block | 515, 2801, 302 |
| 10 | `IMG_1279.JPG` | Portrait of a woman with a full afro and hoop earrings | `portrait-frame-05` (stand-in, see note 1) | 05-moon | 976, 3104, 424 |
| 11 | `IMG_1258.JPG` | Painting of a woman with a very long braid standing in a flower field under a stormy sky | `landscape-frame-02` | 10-vine | 23, 3385, 906 |
| 12 | `IMG_6542.jpg` | Painting of a bride and groom smiling at each other with a bouquet of lilies | `portrait-frame-06` | none | 965, 3737, 449 |
| 13 | `IMG_3DCD4478485B-1.jpeg` | Painting of a woman in a white veil and shawl | `portrait-frame-07` | 06-paper-cotton-flower | 65, 4066, 376 |
| 14 | `IMG_1262.JPG` | Painting of two men in hats, one lighting the other's cigarette | `landscape-frame-02` | 03-flower-base | 524, 4225, 906 |
| 15 | `IMG_6542-design-copy.jpg` | Painting of a bride and groom smiling at each other with a bouquet of lilies | `portrait-frame-06` | none | 28, 4611, 449 |

## B. Photographs that are not in the design layouts

These get a random compatible frame (balanced, never the same frame twice in a row) and are placed below the design block.

| Photograph file | Painting | Frame | Sticker |
|---|---|---|---|
| `F9CF9525-A277-4B7C-808F-2AAEE279B219.jpg` | Portrait of a woman with long wavy blonde hair | `portrait-frame-03` | 10-vine |
| `IMG_0135.jpg` | Portrait of a smiling woman in a white blazer | `portrait-frame-07` | none |
| `IMG_1259.JPG` | Illustrated woman in a yellow halter top beside a tropical bay | `landscape-frame-03` | 05-moon |
| `IMG_1261.JPG` | Painting of a winged figure falling through a red and gold sky | `portrait-frame-06` | 08-paper-rose |
| `IMG_1280.JPG` | Portrait of a woman with short hair, seen in three-quarter view | `portrait-frame-05` | none |
| `IMG_1284.JPG` | Painting of a cowboy riding toward the viewer at sunset | `portrait-frame-02` | none |
| `IMG_1286.JPG` | Painting of an old man in a bowler hat lighting a pipe | `portrait-frame-07` | none |
| `IMG_8807.jpg` | Painting of a cowboy riding toward the viewer at sunset, second version | `portrait-frame-04` | 05-moon |
| `PHOTO-2026-11-09-16-01-34 3.jpg` | Painting of a tennis player lunging for a ball on a red court seen from above | `landscape-frame-03` | none |
| `PHOTO-2026-11-09-16-01-34 18.jpg` | Painting of a man in a blue hat decorated with pink flowers | `portrait-frame-04` | none |
| `PHOTO-2026-11-09-16-01-34 19.jpg` | Painting of a pink flamingo | `portrait-frame-07` | 07-paper-pink-flower |
| `PHOTO-2026-11-09-16-01-34 21.jpg` | Painting of a tennis player serving on a blue court seen from above | `portrait-frame-03` | none |
| `Untitled - 12 February 2024 2.34.JPG` | Portrait of a bearded man with painted marks on his face | `portrait-frame-02` | 04-gold-sun |
| `Untitled - 24 November 2024 10.22.jpg` | Painting of a man and a winged angel wrestling | `portrait-frame-06` | 05-moon |

## Notes

1. **White frame.** The white ornate oval around the afro-haired portrait in the layouts is not among the supplied frame files, so `portrait-frame-05` stands in for it. To use the real one, add a PNG with a transparent window as `frames/portrait-frame-08-white.png`, adjust that entry's `frame_box` in `design.json` if the size differs, and run `python process_images.py`.
2. **Gold sparkles.** The two small four-point stars beside the golden-field painting are not among the sticker files, so they are not shown.
3. **Used twice in the design.** The lady in red (rows 2 and 9) and the wedding couple (rows 12 and 15) each appear in two different frames. Each has a second file in `images/` (`...-design-copy`); keep both.
4. **HEIC photos** (`IMG_0135`, `IMG_2490`, `IMG_3170`, `IMG_6542`, `IMG_8807`) were converted to high-quality JPEG. The script can also read `.heic` directly if `pip install pillow-heif` has been run.
5. **Retired samples.** `landspace_image.png` and `portrait_image.png` were low-resolution placeholders of `IMG_1258` and `IMG_3170` and were removed.
6. The soft light overlay (12%) is applied to every photograph, as requested, so the paintings look slightly softer than in the flat layout image.
7. The captions are in `images/captions.json` (used as alt text). Edit them freely.
