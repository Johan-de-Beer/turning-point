# Stadium and motion

The stadium is original geometry generated with Blender 5.2.2 LTS. `scripts/build_stadium.py` creates the editable `assets/turning-point-stadium.blend` and browser-ready `frontend/public/assets/turning-point-stadium.glb`. It contains a twelve-row seating bowl with aisles, blue and amber seating, spectators, steelwork, two canopies, floodlight lenses, score-screen shells and perimeter LED boards. It contains no fixture or future match data. No stock models or club artwork are used.

Blender was downloaded as a portable Windows ZIP through the Blender mirror network, verified against the Blender release SHA256, and run locally in background mode. The ZIP checksum is `3849d17a682cba006075aaa3f3597ecb5c9c30ec31035b2e092c53e40679b535`. It lives in ignored `.runtime/tools/`; users do not need Blender to run the app. The generated GLB is 4,319,128 bytes, uses ten material batches and has 61,408 source vertices. The `.blend` source is 1,156,850 bytes.

To regenerate with Blender on the command path:

```powershell
blender --background --python scripts/build_stadium.py
```

The browser builds the field and goal frames to a 105 × 68 metre scale with mowing stripes, original turf texture, goal nets and corner flags. Its lighting combines soft directional shadows, roof floodlights and glow sprites. A lightweight stadium is shown while the GLB loads; an SVG pitch remains available when WebGL fails.

Recorded passes and carries reveal their source-to-destination arrows with a moving light. Recorded shots flash rings and a vertical glyph at their source location. These are animated diagrams of already observed events. The application does not invent player positions, interpolate measured tracking, infer an unprovided shot trajectory, or animate future events. The latest eight eligible coordinate-bearing events remain visible; selecting evidence shows its exact historic event. Team-relative coordinates still switch ends at halftime.

The initial empty stadium rotates slowly for an introductory view. During a replay, camera movement is controlled by the user. Dragging changes the view; Top view, Reset and native Fullscreen controls are available. One-finger mobile gestures scroll the page and two fingers control the camera. Reduced motion and the Motion control stop event reveals and introductory camera rotation. Pause freezes event-animation time. Rendering is capped around 30 frames per second and skips hidden/offscreen scenes; pixel ratio is capped at 1.5.

See `verification.md` for actual visual and browser checks. Original generated artwork and the third-party Blender/Three.js tool licenses are distinguished in `licenses.md`.
