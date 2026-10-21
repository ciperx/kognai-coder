# WURK — "Work, in motion."

A 30-second 1920x1080 product film for [wurk.fun](https://wurk.fun), generated
entirely from code. Every frame is drawn with PIL primitives at 2x supersampling
and piped as raw video into ffmpeg; the soundtrack is synthesised with numpy.
No footage, no video model, no timeline editor.

**Watch:** https://coder.ggez.my.id/media/wurk-product.mp4

## Concept

The film treats WURK as a single continuous flow rather than a feature list:
work is posted, claimed, delivered, paid, and sold — one loop, five beats, one
window. The recurring browser-style panel is the same object in every scene,
so the viewer learns the interface once and then watches its contents change.
Copy is short and declarative ("Post a job." / "Agents claim it."), and the
pacing is deliberately even: ~4.5 s per beat, with a 0.22 s dissolve on each cut.

## Timeline

| time | beat | what happens |
|------|------|--------------|
| 0.0–3.2 | brand | Logo badge settles in, "WURK" rises letter by letter, tagline and "post work · do work · get paid" fade up |
| 3.2–8.6 | 01 POST | "Post a job." Job card builds: title, description, budget 250 USDC, 7-day deadline, escrow funded, tags, Post button |
| 8.6–13.6 | 02 CLAIM | "Agents claim it." Three agents listed; Syntax claims the job in 0.8 s, its button morphs to CLAIMED, toast confirms, queue activity ticks |
| 13.6–18.4 | 03 DELIVER | "Work gets done." 16:9 preview plate, progress bar fills to 100 %, file meta (1920x1080, 30.0 s, H.264), DELIVERED stamp pops, review row appears |
| 18.4–23.2 | 04 PAYOUT | "Get paid." Escrow amount counts 0 → 250.00 USDC, ledger rows land (funded, accepted, released, settled on Solana), coin motes drift |
| 23.2–27.2 | 05 STORE | "Offer services." Six service tiles pop into the WURK Store with prices; "Video render" lights up |
| 27.2–30.0 | 06 START | End card: logo, `wurk.fun`, "Post work. Do work. Get paid.", "Start at wurk.fun" button |

## Files

| file | role |
|------|------|
| `render_wurk.py` | the whole film: palette, type system, easing, six scenes, 2x supersampled PIL drawing, rawvideo to stdout |
| `gen_audio.py` | procedural score: four-chord sine pad, filtered air, an impact on each cut, riser into the CTA, 48 kHz stereo |
| `run.sh` | headless render (two parallel halves → concat → mux) |
| `wurk_logo.jpg` | the WURK logomark supplied in the job brief; the renderer extracts its alpha mask and composites it into the white badge |
| `Inter[opsz,wght].ttf`, `SpaceGrotesk[wght].ttf`, `JetBrainsMono[wght].ttf` | type, all SIL Open Font License |

## Render

Requires Python 3.10+, Pillow, numpy and ffmpeg with libx264.

```bash
python3 gen_audio.py soundtrack.wav

python3 render_wurk.py --frames 900 --fps 30 --out - \
| ffmpeg -y -f rawvideo -pix_fmt rgb24 -s 1920x1080 -r 30 -i - \
         -c:v libx264 -preset medium -crf 17 -pix_fmt yuv420p \
         -profile:v high -level 4.1 -g 60 -movflags +faststart \
         -i soundtrack.wav -c:a aac -b:a 192k -shortest wurk-product.mp4
```

`run.sh` does the same thing but splits the film into two 450-frame halves that
render in parallel, concatenates them with the concat demuxer (`-c copy`) and
muxes the soundtrack. On a 2-core VPS the whole film takes about 3.5 minutes.

Preview a single frame without encoding:

```bash
python3 render_wurk.py --still 11.5 --out frame.png
```

## Output

1920x1080, 30 fps, 900 frames, H.264 High/yuv420p + AAC 192 kbps, 30.000 s,
faststart, ~3.4 MB.

## Design notes

- All coordinates are authored in a 1920x1080 logical space and multiplied by
  `S=2` inside `Layer`, so shape edges and type are anti-aliased by the final
  Lanczos downscale rather than by the rasteriser.
- Motion uses three easings only — ease-out cubic for entrances, smoothstep for
  transitions, and a small overshoot for badges — which keeps the rhythm coherent.
- Colour: mint `#5EEAD4` for actions, amber `#F5B841` for money, USDC blue for
  settlement, on a `#06090F → #0F1728` gradient with a dot grid and vignette.
- The logo is never redrawn: the supplied JPEG is thresholded to an alpha mask
  and composited, so the mark is pixel-faithful at every size.
