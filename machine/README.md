# Marble Loop machine (WURK contest entry 160cf6dc42c88806)

Code-driven 20 s seamless loop, 1920x1080, 30 fps, rendered with PIL + numpy and
encoded with ffmpeg. Every moving part is a periodic function of `t` with period
`T = frames / fps`, so the last frame equals the first by construction.

Watch: https://coder.ggez.my.id/media/loop.mp4

    python3 render.py --frames 600 --fps 30 --out - | ffmpeg -f rawvideo -pix_fmt rgb24 \
      -s 1920x1080 -r 30 -i - -c:v libx264 -pix_fmt yuv420p -crf 20 loop.mp4

Mechanism: three balls ride one closed circuit (lift column with scoops -> top rail
-> curved chute -> conveyor back to the lift), driven by a gear train whose rotation
is exactly one turn per loop; the pendulum at the drop point swings three times per
loop, one knock per ball.
