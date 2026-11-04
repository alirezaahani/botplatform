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

Pair an answer with its puzzle by `challenge_id`: `puzzle_captured.challenge_id` equals `answer_request.request.challenge_id`. Do not pair by event order, because a fast answer can be logged before the capture of the same poll. The `answer` record is unchanged: `request.answers` is the slider x and `response.success` is the label (true means the position was right).

## Making labeled samples from assisted runs

1. Run `arcaptcha-assisted` and solve the slider by hand.
2. For each `puzzle_captured` n, take the next `answer_request`: `answers` is the slider x, `success` says whether it was right.
3. A sample is (background image, piece image, piece `top`, `answers`). Rows with `success: true` are positive labels. A `false` row only says that x was wrong.
4. The slider x and the piece's `left` may differ by a scale or offset. Check this with `slider_candidates` and the final piece position before training on it.

## The drag probe experiment (`arcaptcha-drag-probe`)

An experiment, not a solver. Headful, profile `all-signals`. It ticks the checkbox and, if a puzzle appears, makes up to 8 attempts (limit and a 100 s budget are in `StepTimeouts`), one per puzzle. Attempt i uses method `selenium` (ActionChains press, 8 moves, release) when i is even and `cdp` (`Input.dispatchMouseEvent`) when odd, with dx 40, 80, 120, 150, 180, 200, 240, 300 px (the last ones over-travel on purpose). Puzzle n is captured before attempt n's drag. The answer is never read to decide anything, except that `success: true` is recorded and ends the probe. The run always ends `blocked` / `drag_probe_done`, never as a solve. Then the normal login runs, as for every bot.

Events: `drag_probe_started` (plan), `drag_probe_attempt` per attempt, `drag_probe_failed` (type, message; the probe goes on, and stops after two failures in a row), `drag_probe_finished` (`reason`: `plan_finished`, `budget_spent`, `answer_accepted`, `no_answer`, `no_new_puzzle`, `repeated_failures`, `no_puzzle`). The `answer_request` events are recorded as usual.

A `drag_probe_attempt` holds `n`, `challenge_id`, `method`, `dx`, `error`, `outcome` (`next_puzzle`, `no_answer`, `no_new_puzzle`), `samples`, `after_outcome` (state once the answer and next puzzle arrived, so usually the new puzzle) and `listener`. Each sample (`before`, `pressed`, 8 x `step`, `released`; `moved` is the requested px) has `handle`, `piece` and `piece_parent`, each with `rect`, inline `style_left`/`style_transform` and `computed_left`/`computed_transform`.

How to read it:

- Ratio handle to piece: for the `released` sample, (piece `computed_left`) / (handle `computed_left`), or the rect `x` change of each. Check it at several dx, and at the over-travel ones for the clamp of each (about 196 px for the handle was seen).
- `answers`: pair `answer_request.request.answers` with the attempt by `challenge_id`. Compare it to the piece's final left, the handle's final left, and `dx`. If the handle did not move (`released` equals `before`), the widget ignored that method.
- Event family: `listener` counts, per event type, `count`, the first 5 `isTrusted` values and the first 3 targets. Mouse, pointer, touch or drag types with counts above zero show what reached the page; this says what the widget could listen to, not what it does. Look at `targets` for the element receiving the press.
- Trusted: `isTrusted` false for an event type means the browser marked it synthetic. CDP and WebDriver input normally give true.

Not verified against the real site: the selectors `div.draggable` and `img.puzzle`, and whether either method moves the real handle.
