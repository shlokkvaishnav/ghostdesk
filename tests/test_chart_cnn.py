"""Chart images and the CNN: an image ending on a session uses only bars up to it, its layout follows the paper,
bad windows give no image, training labels never reach the predicted months, and the network learns a planted
pattern."""
import numpy as np
import pandas as pd
import pytest

from ghostdesk.return_models import chart_cnn
from ghostdesk.return_models.chart_images import DAYS, HEIGHT, PRICE_ROWS, VOLUME_ROWS, WIDTH, draw, matrices, windows

DAYS_IDX = pd.bdate_range("2019-01-01", periods=120)


def data(seed=0, syms=("A", "B")):
    rng = np.random.default_rng(seed)
    rows = []
    for s in syms:
        c = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, len(DAYS_IDX))))
        rows.append(pd.DataFrame({"symbol": s, "day": DAYS_IDX, "o": c * 1.001, "h": c * 1.01, "l": c * 0.99, "c": c,
                                  "v": rng.integers(1e5, 1e6, len(DAYS_IDX)).astype(float), "flag": False}))
    d = pd.concat(rows, ignore_index=True)
    d["t"] = (d["day"] + pd.Timedelta(hours=5)).dt.tz_localize("UTC")
    return d[["symbol", "t", "o", "h", "l", "c", "v"]], d[["symbol", "day", "flag"]]


def test_an_image_uses_only_bars_up_to_its_last_session():
    prices, ret = data()
    end = 60
    a, ok = windows(matrices(prices, ret), ["A"], [end])
    later = prices["t"] > (DAYS_IDX[end] + pd.Timedelta(hours=5)).tz_localize("UTC")
    p2 = prices.copy()
    p2.loc[later, ["o", "h", "l", "c", "v"]] *= 5
    b, ok2 = windows(matrices(p2, ret), ["A"], [end])
    assert ok[0] and ok2[0] and np.array_equal(draw(a), draw(b))


def test_layout_open_bar_close_and_volume():
    a = {"o": np.full((1, DAYS), 10.0), "h": np.full((1, DAYS), 12.0), "l": np.full((1, DAYS), 8.0),
         "c": np.full((1, DAYS), 11.0), "ma": np.full((1, DAYS), 10.0), "v": np.ones((1, DAYS))}
    a["h"][0, 5], a["v"][0, 7] = 20.0, 2.0  # the highest high; the largest volume
    img = draw(a)[0]
    assert img.shape == (HEIGHT, WIDTH)
    assert img[0, 3 * 5 + 1] == 255 and img[0].sum() == 255  # only day 5's bar reaches the top row
    assert img[PRICE_ROWS - 1, 1] == 255  # the lowest low (8) is the bottom price row
    assert img[PRICE_ROWS, :].sum() == 0  # the gap row
    assert img[HEIGHT - VOLUME_ROWS:, 3 * 7 + 1].all() and img[HEIGHT - VOLUME_ROWS - 1, 3 * 7 + 1] == 0
    assert img[HEIGHT - VOLUME_ROWS:, 0].sum() == 0  # volume only in the middle column
    r_open = round((20 - 10) / 12 * (PRICE_ROWS - 1))
    assert img[r_open, 0] == 255 and img[round((20 - 11) / 12 * (PRICE_ROWS - 1)), 2] == 255


def test_bad_windows_give_no_image():
    prices, ret = data()
    ret.loc[(ret["symbol"] == "A") & (ret["day"] == DAYS_IDX[50]), "flag"] = True
    prices = prices[~((prices["symbol"] == "B") & (prices["t"].dt.tz_localize(None).dt.normalize() == DAYS_IDX[55]))]
    m = matrices(prices, ret)
    _, ok = windows(m, ["A", "A", "B", "B", "A", "Z"], [60, 80, 60, 95, 45, 60], [0, 0, 0, 0, 30, 0])
    # A at 60 has the flagged day; B at 60 a missing bar (and B needs 20 clean bars before its window for the
    # moving average, so 95 is its first good end after the gap); A at 45 starts before its interval (30 + 20 > 26 + 20);
    # Z is unknown
    assert ok.tolist() == [False, True, False, True, False, False]


def test_training_labels_end_before_the_predicted_months():
    prices, ret = data()
    m = matrices(prices, ret)
    members = pd.DataFrame({"price_symbol": ["A", "B"], "start": [DAYS_IDX[0], DAYS_IDX[70]], "end": pd.NaT})
    x, y, keys = chart_cnn.training_images(m, members, DAYS_IDX[0], DAYS_IDX[-1], DAYS_IDX[99], step=1)
    pos = DAYS_IDX.get_indexer(keys["day"])
    assert len(x) and (pos + DAYS <= 99).all()  # every label window ends by the label end
    assert (keys.loc[keys["symbol"] == "B", "day"] >= DAYS_IDX[70 + DAYS - 1]).all()  # members only, whole window
    assert set(y) <= {0, 1} and np.array_equal(y, (keys["fwd"] > 0).astype(int).to_numpy())


def test_the_network_learns_a_planted_pattern():
    pytest.importorskip("torch")
    rng = np.random.default_rng(0)
    x = (rng.random((600, HEIGHT, WIDTH)) < 0.05).astype(np.uint8) * 255
    y = rng.integers(0, 2, 600)
    x[y == 1, :8, -6:] = 255  # "up" images have a bright top-right corner
    cfg = chart_cnn.TRAIN | {"channels": (4, 8, 8), "max_epochs": 4, "lr": 3e-3, "batch": 64}
    model, hist = chart_cnn.fit(x, y, seed=0, cfg=cfg, log=lambda m: None)
    p = chart_cnn.predict([model], x)
    assert len(hist) >= 1 and ((p > 0.5) == y).mean() > 0.9
