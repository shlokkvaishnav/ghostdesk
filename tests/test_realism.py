"""Realism checks (stylised facts, discriminator) on synthetic series."""
import numpy as np

from ghostdesk.execution.realism import discriminator_score, stylised_facts


def test_stylised_facts_and_discriminator():
    rng = np.random.default_rng(0)
    iid = rng.standard_normal(50_000)
    f = stylised_facts(iid)
    assert abs(f["kurt_1"]) < 0.2 and abs(f["acf_abs_1"]) < 0.03
    vol = np.exp(np.convolve(rng.standard_normal(50_000), np.ones(200) / 20, "same"))  # slow volatility
    g = stylised_facts(vol * rng.standard_normal(50_000))
    assert g["kurt_1"] > 1 and g["acf_abs_10"] > 0.1 and g["hill"] < f["hill"]
    real = rng.standard_normal((200, 50, 2))
    assert abs(discriminator_score(real, rng.standard_normal((200, 50, 2))) - 0.5) < 0.1
    assert discriminator_score(real, 1.5 * rng.standard_normal((200, 50, 2))) > 0.9
