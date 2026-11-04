# Puzzle capture: data for a slider solver

Every bot that uses the ARCaptcha scenario (not only `arcaptcha-assisted`) captures each puzzle it sees. A failed capture is recorded and never changes the run's result.

## What is captured, per puzzle n (counted from 1 in the run)

- Artifacts `puzzle-<n>-background.<ext>` and `puzzle-<n>-piece.<ext>`. The bytes are fetched by `fetch(src)` inside the page, so the request has the browser's origin and cookies. The extension and content type come from the bytes.
- A `puzzle_captured` event with: `challenge_id` (of the latest `create`), `n`, the artifact names, and for each image its `src`, `natural_width`/`natural_height` and on-screen `rect`. The piece also has its inline `style_left`/`style_top` and `computed_left`/`computed_top`. The event also holds `wrapper_rect` (the background's parent), `piece_parent_rect`, `slider_candidates` and `device_pixel_ratio`.
- If the images do not load in time or the fetch fails, a `puzzle_capture_failed` event with `challenge_id`, `n` and the error type.

## Not verified against the real site

- The piece is found as `img.puzzle`, the background as the other `img` whose `src` contains `/puzzles/`. Both come from the DOM seen by hand, not from a captured run.
- The slider's selectors are unknown. `slider_candidates` lists up to 10 elements whose class name contains `slider`, `handle`, `track` or `drag`, with their rects. Read it from the first live run and replace it with real selectors.

## Pairing a puzzle with its answer

Events are in order. The `answer_request` events after `puzzle_captured` n and before `puzzle_captured` n+1 belong to puzzle n. The `answer` record is unchanged: `request.answers` is the slider x and `response.success` is the label (true means the position was right).

## Making labeled samples from assisted runs

1. Run `arcaptcha-assisted` and solve the slider by hand.
2. For each `puzzle_captured` n, take the next `answer_request`: `answers` is the slider x, `success` says whether it was right.
3. A sample is (background image, piece image, piece `top`, `answers`). Rows with `success: true` are positive labels. A `false` row only says that x was wrong.
4. The slider x and the piece's `left` may differ by a scale or offset. Check this with `slider_candidates` and the final piece position before training on it.
