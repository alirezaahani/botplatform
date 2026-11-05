"""The path generators, and a real drag on a plain slider page."""

import itertools
import random

import pytest
from selenium.webdriver.common.by import By

from botplatform.bots.utils.drag import MOVERS, duration, eased_path, linear_path, perform_drag

DXS = [0, 1, 7, 90, 130, 196]


def test_the_registry_names():
    assert MOVERS == {"linear": linear_path, "eased": eased_path}


@pytest.mark.parametrize("dx", DXS)
def test_both_paths_end_exactly_at_dx(dx):
    assert linear_path(dx)[-1][0] == dx
    for seed in range(20):
        assert eased_path(dx, random.Random(seed))[-1][0] == dx


@pytest.mark.parametrize("dx", [8, 90, 196])
def test_linear_is_eight_equal_steps_at_an_equal_pace(dx):
    path = linear_path(dx)
    assert len(path) == 8
    xs = [0] + [x for x, _, _ in path]
    steps = [b - a for a, b in itertools.pairwise(xs)]
    assert max(steps) - min(steps) <= 1  # rounding only
    assert len({pause for _, _, pause in path}) == 1
    assert all(y == 0 for _, y, _ in path)
    assert 0.5 <= duration(path) <= 0.8


def test_eased_slows_down_and_never_goes_back_or_past_dx():
    for seed in range(50):
        path = eased_path(150, random.Random(seed))
        xs = [x for x, _, _ in path]
        assert xs == sorted(xs)
        assert max(xs) == 150
        assert xs[0] > xs[-1] - xs[-2]  # the first step is larger than the last
        assert path[-1][1] == 0


def test_eased_duration_steps_and_wobble_are_bounded():
    for seed in range(100):
        path = eased_path(120, random.Random(seed))
        assert 25 <= len(path) <= 40
        assert 0.8 <= duration(path) <= 1.5 + 1e-9
        assert all(abs(y) <= 2 for _, y, _ in path)
        assert all(pause > 0 for _, _, pause in path)


def test_the_same_seed_repeats_and_different_seeds_differ():
    assert eased_path(100, random.Random(1)) == eased_path(100, random.Random(1))
    paths = {tuple(eased_path(100, random.Random(seed))) for seed in range(10)}
    assert len(paths) == 10


def test_edge_distances():
    assert [x for x, _, _ in linear_path(0)] == [0] * 8
    assert eased_path(0, random.Random(3))[-1][0] == 0
    assert eased_path(196, random.Random(3))[-1][0] == 196


# -- A real drag -----------------------------------------------------------------------------------

# A handle that follows the pointer while pressed, unless `window.ignorePresses` is set.
SLIDER = """<!doctype html>
<div id="handle" style="position:absolute;left:0;top:100px;width:40px;height:40px"></div>
<script>
const handle = document.getElementById('handle');
let start = null;
handle.addEventListener('mousedown', (e) => { if (!window.ignorePresses) start = e.clientX; });
document.addEventListener('mousemove', (e) => {
  if (start !== null) handle.style.left = (e.clientX - start) + 'px';
});
document.addEventListener('mouseup', () => { start = null; });
</script>"""
LEFT_JS = "return parseFloat(document.getElementById('handle').style.left) || 0"
DX = 120


def drag_handle(driver, mover: str):
    return perform_drag(
        driver,
        driver.find_element(By.ID, "handle"),
        MOVERS[mover](DX, random.Random(1)),
        lambda: {"left": driver.execute_script(LEFT_JS)},
        lambda snapshot: snapshot["left"] > 0,
    )


@pytest.mark.parametrize("mover", list(MOVERS))
def test_a_drag_moves_the_handle_by_dx(driver, local_page, mover):
    local_page.html = SLIDER
    driver.get(local_page.url)

    result = drag_handle(driver, mover)

    assert result.moved
    assert result.final == {"left": DX}


def test_a_handle_that_ignores_the_press_stops_the_drag_early(driver, local_page):
    local_page.html = SLIDER
    driver.get(local_page.url)
    driver.execute_script("window.ignorePresses = true")

    result = drag_handle(driver, "linear")

    assert not result.moved
    assert result.final == {"left": 0}
