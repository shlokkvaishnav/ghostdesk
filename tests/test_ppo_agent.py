import gymnasium as gym
import numpy as np
import pytest

torch = pytest.importorskip("torch")
from ghostdesk.execution.ppo_agent import PPO, PPOConfig, gae


def test_gae_matches_hand_computation_and_stops_at_episode_end():
    r = np.array([1.0, 1.0, 1.0], np.float32)
    v = np.array([0.5, 0.5, 0.5], np.float32)
    d = np.array([0, 1, 0], np.float32)  # the episode ends after step 1
    adv, ret = gae(r, v, d, last_value=2.0, gamma=0.9, lam=1.0)
    # step 1 is terminal: adv = 1 - 0.5; step 0: delta0 + 0.9 * adv1; step 2 bootstraps from last_value
    assert np.isclose(adv[1], 0.5) and np.isclose(adv[0], (1 + 0.9 * 0.5 - 0.5) + 0.9 * 0.5)
    assert np.isclose(adv[2], 1 + 0.9 * 2.0 - 0.5) and np.allclose(ret, adv + v)


class Bandit(gym.Env):
    """One-step task: reward = -(a - 0.7)^2. The optimal deterministic action is 0.7."""

    observation_space = gym.spaces.Box(-1, 1, (1,), np.float32)
    action_space = gym.spaces.Box(-1, 1, (1,), np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        return np.zeros(1, np.float32), {}

    def step(self, a):
        return np.zeros(1, np.float32), -float((a[0] - 0.7) ** 2), True, False, {}


def test_ppo_learns_a_continuous_bandit():
    agent = PPO(Bandit(), PPOConfig(n_steps=256, batch=64, epochs=10, lr=3e-3), seed=0).learn(6000)
    a, _, _ = agent.model.act(np.zeros(1, np.float32), deterministic=True)
    assert abs(a[0] - 0.7) < 0.1


def test_ppo_improves_on_cartpole_quickly():
    env = gym.make("CartPole-v1")
    agent = PPO(env, PPOConfig(n_steps=512, lr=1e-3), seed=0)
    before = agent.evaluate(gym.make("CartPole-v1"), episodes=5).mean()
    agent.learn(15_000)
    after = agent.evaluate(gym.make("CartPole-v1"), episodes=5).mean()
    assert after > max(2 * before, 100)
