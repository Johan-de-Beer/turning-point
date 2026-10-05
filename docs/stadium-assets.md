# Stadium and motion

The stadium is original geometry generated with Blender 5.2.2 LTS. `scripts/build_stadium.py` creates the editable `assets/turning-point-stadium.blend` and browser-ready `frontend/public/assets/turning-point-stadium.glb`. It contains a twelve-row seating bowl with aisles, blue and amber seating, spectators, steelwork, two canopies, floodlight lenses, score-screen shells and perimeter LED boards. It contains no fixture or future match data. No stock models or club artwork are used.

Blender was downloaded as a portable Windows ZIP through the Blender mirror network, verified against the Blender release SHA256, and run locally in background mode. The ZIP checksum is `3849d17a682cba006075aaa3f3597ecb5c9c30ec31035b2e092c53e40679b535`. It lives in ignored `.runtime/tools/`; users do not need Blender to run the app. The generated GLB is 4,319,128 bytes, uses ten material batches and has 61,408 source vertices. The `.blend` source is 1,156,850 bytes.

To regenerate with Blender on the command path:

```powershell
blender --background --python scripts/build_stadium.py
```

The browser builds the field and goal frames to a 105 × 68 metre scale with mowing stripes, original turf texture, goal nets and corner flags. Its lighting combines soft directional shadows, roof floodlights and glow sprites. A lightweight stadium is shown while the GLB loads; an SVG pitch remains available when WebGL fails.

The pitch replays delivered actions sequentially with one textured football. Passes and carries move between their recorded start and end; shots move from their recorded position to an optional recorded target. A shot without a target stays at its known origin. An actor marker uses the recorded source, follows the ball for a carry, and a completed-pass recipient marker uses the recorded endpoint. Player names, action/outcome and event time identify the active record. These markers are event participants at known points, not continuous player tracking or an inferred formation. Stoppage and period markers hide the ball. Team-relative coordinates switch physical ends using each event's own period.

The full canonical delivered event set feeds a separate playback queue; the recent-events list is only a display. Transport identity/revision prevents repeated polling from replaying old actions, and retractions remove unsupported actions. Restart clears the old generation. Reload shows the latest known position rather than animating the full past prefix. Selected evidence remains a separate immutable event version; clearing inspection restores the live frame and queue. `Replay this event` explicitly plays that selected record while the server replay clock stays unchanged.

At the default 12× speed, illustrative diagram durations are 0.85 seconds for a pass, 1.1 seconds for a carry and 0.75 seconds for a shot. Higher replay speeds and queue catch-up shorten visual duration. These durations and arced drawing effects are not measured ball-flight times or trajectories. The recorded timestamp remains visible even when the diagram queue trails the observed server cutoff. No future event, guessed shot target or unobserved off-ball position is introduced.

The initial empty stadium rotates slowly for an introductory view. During a replay, camera movement is controlled by the user. Dragging changes the view; Top view, Reset and native Fullscreen controls are available. One-finger mobile gestures scroll the page and two fingers control the camera. Reduced motion and the Motion control show static observed endpoints and stop introductory rotation; incoming observed data can still update while playing. An ordinary pause freezes the live event, route progress and ball position. Half-time/full-time may finish the already delivered action queue before showing the period-end marker. Rendering is capped around 30 frames per second and skips hidden/offscreen scenes; pixel ratio is capped at 1.5.

See `verification.md` for actual visual and browser checks. Original generated artwork and the third-party Blender/Three.js tool licenses are distinguished in `licenses.md`.
