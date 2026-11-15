"""PPO written from scratch (Schulman et al. 2017), with the settings of reports/spec_01.md.

One environment, rollouts of `n_steps`, GAE, clipped surrogate, separate actor and critic MLPs (64-64 tanh),
advantages normalised per minibatch, gradient clipping. Discrete actions: categorical policy. Box actions: Gaussian
with a state-independent log std; sampled actions are clipped to the bounds only when sent to the environment, and
the log-probability uses the unclipped sample (as Stable-Baselines3 does). Truncated episodes bootstrap from the value
of the final observation.
"""
from __future__ import annotations

from dataclasses import dataclass

import gymnasium as gym
import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical, Normal


@dataclass
class PPOConfig:
    n_steps: int = 2048
    epochs: int = 10
    batch: int = 64
    lr: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip: float = 0.2
    vf_coef: float = 0.5
    ent_coef: float = 0.0
    max_grad_norm: float = 0.5


def mlp(i, o, out_gain=1.0):
    layers = [nn.Linear(i, 64), nn.Tanh(), nn.Linear(64, 64), nn.Tanh(), nn.Linear(64, o)]
    for layer in layers[:-1:2]:
        nn.init.orthogonal_(layer.weight, np.sqrt(2))
        nn.init.zeros_(layer.bias)
    nn.init.orthogonal_(layers[-1].weight, out_gain)
    nn.init.zeros_(layers[-1].bias)
    return nn.Sequential(*layers)


class ActorCritic(nn.Module):
    def __init__(self, obs_space: gym.Space, act_space: gym.Space):
        super().__init__()
        n_obs = int(np.prod(obs_space.shape))
        self.discrete = isinstance(act_space, gym.spaces.Discrete)
        n_act = act_space.n if self.discrete else int(np.prod(act_space.shape))
        self.pi = mlp(n_obs, n_act, 0.01)
        self.v = mlp(n_obs, 1, 1.0)
        if not self.discrete:
            self.log_std = nn.Parameter(torch.zeros(n_act))

    def dist(self, obs):
        out = self.pi(obs)
        return Categorical(logits=out) if self.discrete else Normal(out, self.log_std.exp())

    def value(self, obs):
        return self.v(obs).squeeze(-1)

    @torch.no_grad()
    def act(self, obs: np.ndarray, deterministic: bool = False):
        o = torch.as_tensor(obs, dtype=torch.float32)[None]
        d = self.dist(o)
        if deterministic:
            a = d.probs.argmax(-1) if self.discrete else d.mean
        else:
            a = d.sample()
        lp = d.log_prob(a) if self.discrete else d.log_prob(a).sum(-1)
        return a[0].numpy(), float(lp[0]), float(self.value(o)[0])


def gae(rewards, values, dones, last_value, gamma, lam):
    """dones[t] = 1 if the episode ended (terminated) after step t; values[t] = V(s_t)."""
    adv = np.zeros_like(rewards)
    last = 0.0
    for t in reversed(range(len(rewards))):
        next_v = last_value if t == len(rewards) - 1 else values[t + 1]
        nonterm = 1.0 - dones[t]
        delta = rewards[t] + gamma * next_v * nonterm - values[t]
        last = delta + gamma * lam * nonterm * last
        adv[t] = last
    return adv, adv + values


class PPO:
    def __init__(self, env: gym.Env, cfg: PPOConfig | None = None, seed: int = 0):
        self.env, self.cfg, self.seed = env, cfg or PPOConfig(), seed
        torch.manual_seed(seed)
        np.random.seed(seed)
        self.model = ActorCritic(env.observation_space, env.action_space)
        self.opt = torch.optim.Adam(self.model.parameters(), lr=self.cfg.lr, eps=1e-5)
        self.box = isinstance(env.action_space, gym.spaces.Box)
        self.episode_returns: list[float] = []

    def _to_env(self, a):
        return np.clip(a, self.env.action_space.low, self.env.action_space.high) if self.box else int(a)

    def learn(self, total_steps: int, log=None):
        c, env = self.cfg, self.env
        obs, _ = env.reset(seed=self.seed)
        ep_ret, steps = 0.0, 0
        while steps < total_steps:
            buf = {k: [] for k in ("obs", "act", "logp", "rew", "val", "done")}
            for _ in range(c.n_steps):
                a, lp, v = self.model.act(obs)
                nxt, r, term, trunc, _ = env.step(self._to_env(a))
                if trunc and not term:  # bootstrap a time-limit cut from the value of the cut state
                    r = r + c.gamma * self.model.act(nxt)[2]
                for k, x in zip(buf, (obs, a, lp, r, v, float(term or trunc)), strict=True):
                    buf[k].append(x)
                ep_ret += r
                obs = nxt
                steps += 1
                if term or trunc:
                    self.episode_returns.append(ep_ret)
                    ep_ret = 0.0
                    obs, _ = env.reset()
            last_v = self.model.act(obs)[2]
            arr = {k: np.asarray(v, np.float32) for k, v in buf.items()}
            adv, ret = gae(arr["rew"], arr["val"], arr["done"], last_v, c.gamma, c.gae_lambda)
            self._update(arr, adv, ret)
            if log and self.episode_returns:
                log(f"steps {steps}: mean return of last 10 episodes {np.mean(self.episode_returns[-10:]):.3f}")
        return self

    def _update(self, arr, adv, ret):
        c = self.cfg
        obs = torch.as_tensor(arr["obs"]).reshape(len(adv), -1)
        act = torch.as_tensor(arr["act"])
        old_lp = torch.as_tensor(arr["logp"])
        adv_t, ret_t = torch.as_tensor(adv), torch.as_tensor(ret)
        n = len(adv)
        for _ in range(c.epochs):
            for idx in torch.randperm(n).split(c.batch):
                d = self.model.dist(obs[idx])
                lp = d.log_prob(act[idx].long()) if self.model.discrete else d.log_prob(act[idx]).sum(-1)
                ent = d.entropy() if self.model.discrete else d.entropy().sum(-1)
                a = adv_t[idx]
                a = (a - a.mean()) / (a.std() + 1e-8) if len(idx) > 1 else a
                ratio = torch.exp(lp - old_lp[idx])
                pg = -torch.min(ratio * a, torch.clamp(ratio, 1 - c.clip, 1 + c.clip) * a).mean()
                vf = ((self.model.value(obs[idx]) - ret_t[idx]) ** 2).mean()
                loss = pg + c.vf_coef * vf - c.ent_coef * ent.mean()
                self.opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.model.parameters(), c.max_grad_norm)
                self.opt.step()

    def evaluate(self, env: gym.Env, episodes: int = 20, seed: int = 10_000) -> np.ndarray:
        out = []
        for i in range(episodes):
            o, _ = env.reset(seed=seed + i)
            total, done = 0.0, False
            while not done:
                a, _, _ = self.model.act(o, deterministic=True)
                o, r, term, trunc, _ = env.step(self._to_env(a))
                total += r
                done = term or trunc
            out.append(total)
        return np.asarray(out)
