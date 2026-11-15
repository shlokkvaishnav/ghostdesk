"""Learned order-book world model (reports/spec_03.md): a GRU over per-second categorical tokens.

At second t the model has seen tokens 0..t-1 (state h_{t-1}):
1. the flow head samples the buy and sell bins of second t;
2. an agent's market sale of v is added to the sell volume (bin centre + v, binned again);
3. the state head, given h_{t-1} and the flow of second t, samples move, spread and the two imbalances.
So the price reacts to the agent the way it reacts to all aggressive selling in the training data.
The Markov baseline of the spec is `Markov`; both expose `move_nll(tokens)` for rule 1.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from ..data.tokens import FIELDS, MAX_MOVE, SIZES, VolumeBins

EMB, HID = 64, 128
FLOW = ("buy", "sell")
STATE = ("move", "spread", "imb1", "imb5")
IDX = {f: i for i, f in enumerate(FIELDS)}


class WorldModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.emb = nn.ModuleDict({f: nn.Embedding(SIZES[f], EMB) for f in FIELDS})
        self.flow_emb = nn.ModuleDict({f: nn.Embedding(SIZES[f], EMB) for f in FLOW})
        self.gru = nn.GRU(EMB, HID, num_layers=2, batch_first=True)
        self.flow_head = nn.Linear(HID, sum(SIZES[f] for f in FLOW))
        self.state_head = nn.Sequential(nn.Linear(HID + EMB, HID), nn.GELU(), nn.Linear(HID, sum(SIZES[f] for f in STATE)))
        self.h0 = nn.Parameter(torch.zeros(2, 1, HID))

    def embed(self, tok):  # (B, T, 6) -> (B, T, EMB)
        return sum(self.emb[f](tok[..., IDX[f]]) for f in FIELDS)

    def flow_cond(self, buy, sell):
        return self.flow_emb["buy"](buy) + self.flow_emb["sell"](sell)

    @staticmethod
    def split(logits, fields):
        out, i = {}, 0
        for f in fields:
            out[f] = logits[..., i: i + SIZES[f]]
            i += SIZES[f]
        return out

    def forward(self, tok):
        """Teacher-forced logits for rows 1..T-1 of tok (B, T, 6)."""
        h, _ = self.gru(self.embed(tok[:, :-1]), self.h0.expand(-1, tok.shape[0], -1).contiguous())
        nxt = tok[:, 1:]
        flow = self.split(self.flow_head(h), FLOW)
        state = self.split(self.state_head(torch.cat([h, self.flow_cond(nxt[..., 0], nxt[..., 1])], -1)), STATE)
        return {**flow, **state}

    def loss(self, tok):
        lg = self.forward(tok)
        nxt = tok[:, 1:]
        return sum(F.cross_entropy(lg[f].reshape(-1, SIZES[f]), nxt[..., IDX[f]].reshape(-1)) for f in FIELDS)

    @torch.no_grad()
    def move_nll(self, tok: np.ndarray, chunk: int = 3600) -> np.ndarray:
        """Per-second NLL of the move given the past and the flow of the same second; the GRU state carries over
        chunks, so this is exact for the whole day. Returns NLL for rows 1..T-1."""
        self.eval()
        t = torch.as_tensor(tok)[None]
        hidden, out = self.h0.contiguous(), []
        prev = t[:, :1]
        for s in range(1, t.shape[1], chunk):
            cur = t[:, s: s + chunk]
            inp = torch.cat([prev, cur[:, :-1]], 1)
            h, hidden = self.gru(self.embed(inp), hidden)
            st = self.split(self.state_head(torch.cat([h, self.flow_cond(cur[..., 0], cur[..., 1])], -1)), STATE)
            out.append(-F.log_softmax(st["move"], -1).gather(-1, cur[..., IDX["move"], None])[0, :, 0])
            prev = cur[:, -1:]
        return torch.cat(out).numpy()

    @torch.no_grad()
    def rollout(self, context: np.ndarray, steps: int, bins: VolumeBins, agent_sell: np.ndarray | None = None,
                seed: int = 0) -> np.ndarray:
        """context: (B, C, 6) real tokens; returns generated tokens (B, steps, 6). agent_sell: (B, steps) volumes added
        to the sampled market sell volume (None = no agent)."""
        self.eval()
        g = torch.Generator().manual_seed(seed)
        ctx = torch.as_tensor(context)
        B = ctx.shape[0]
        hidden = self.h0.expand(-1, B, -1).contiguous()
        if ctx.shape[1] > 1:  # consume rows 0..C-2; the loop feeds the last context row
            _, hidden = self.gru(self.embed(ctx[:, :-1]), hidden)
        last, out = ctx[:, -1], []
        centers = torch.as_tensor(np.nan_to_num(bins.centers), dtype=torch.float64)
        for k in range(steps):
            h, hidden = self.gru(self.embed(last[:, None]), hidden)
            h = h[:, 0]
            fl = self.split(self.flow_head(h), FLOW)
            buy = torch.multinomial(F.softmax(fl["buy"], -1), 1, generator=g)[:, 0]
            sell = torch.multinomial(F.softmax(fl["sell"], -1), 1, generator=g)[:, 0]
            if agent_sell is not None:
                vol = centers[sell] + torch.as_tensor(agent_sell[:, k], dtype=torch.float64)
                sell = torch.as_tensor(bins(vol.numpy()))
            st = self.split(self.state_head(torch.cat([h, self.flow_cond(buy, sell)], -1)), STATE)
            draws = [torch.multinomial(F.softmax(st[f], -1), 1, generator=g)[:, 0] for f in STATE]
            last = torch.stack([buy, sell, *draws], -1)
            out.append(last)
        return torch.stack(out, 1).numpy()


def windows(days: list[np.ndarray], n: int, length: int, rng: np.random.Generator) -> np.ndarray:
    """n random windows of `length` rows, days chosen in proportion to their length."""
    lens = np.array([len(d) - length for d in days])
    which = rng.choice(len(days), n, p=lens / lens.sum())
    return np.stack([days[d][s: s + length] for d, s in zip(which, (rng.integers(0, lens[w]) for w in which), strict=True)])


def train_world_model(days: list[np.ndarray], seed: int = 0, epochs: int = 10, per_epoch: int = 20_000,
                      batch: int = 64, length: int = 300, lr: float = 1e-3, log=print) -> WorldModel:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = WorldModel()
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    model.train()
    for ep in range(epochs):
        w = torch.as_tensor(windows(days, per_epoch, length, rng))
        losses = []
        for i in range(0, per_epoch, batch):
            loss = model.loss(w[i: i + batch])
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            losses.append(loss.item())
        log(f"seed {seed} epoch {ep + 1}/{epochs}: loss {np.mean(losses):.4f}")
    model.eval()
    return model


class Markov:
    """(move, spread) given previous (move, spread) and the current (sell, buy) bins. Smoothing (spec 03, A2): one
    pseudo-count per context in total, spread over the outcomes in proportion to the train-day marginal.
    Generation samples the flow from the train-day marginal (independent of the state)."""

    def __init__(self, days: list[np.ndarray]):
        nm, ns, nb = SIZES["move"], SIZES["spread"], SIZES["sell"]
        self.shape = (nm, ns, nb, nb)
        self.counts = np.zeros(self.shape + (nm * ns,))
        flow = np.zeros((nb, nb))
        for d in days:
            ctx = self._ctx(d[:-1], d[1:])
            out = d[1:, IDX["move"]] * ns + d[1:, IDX["spread"]]
            np.add.at(self.counts, (*ctx, out), 1)
            np.add.at(flow, (d[:, IDX["sell"]], d[:, IDX["buy"]]), 1)
        marginal = self.counts.sum(axis=(0, 1, 2, 3))
        self.counts += marginal / marginal.sum()
        self.p = self.counts / self.counts.sum(-1, keepdims=True)
        self.flow = (flow / flow.sum()).ravel()

    @staticmethod
    def _ctx(prev, cur):
        return prev[:, IDX["move"]], prev[:, IDX["spread"]], cur[:, IDX["sell"]], cur[:, IDX["buy"]]

    def move_nll(self, tok: np.ndarray) -> np.ndarray:
        p = self.p[self._ctx(tok[:-1], tok[1:])].reshape(len(tok) - 1, SIZES["move"], SIZES["spread"]).sum(-1)
        return -np.log(p[np.arange(len(p)), tok[1:, IDX["move"]]])

    def rollout(self, context: np.ndarray, steps: int, seed: int = 0) -> np.ndarray:
        rng = np.random.default_rng(seed)
        B, ns, nb = len(context), SIZES["spread"], SIZES["sell"]
        out = np.zeros((B, steps, len(FIELDS)), np.int64)
        prev = context[:, -1]
        cum = self.p.cumsum(-1)
        for k in range(steps):
            f = rng.choice(nb * nb, B, p=self.flow)
            sell, buy = f // nb, f % nb
            c = cum[prev[:, IDX["move"]], prev[:, IDX["spread"]], sell, buy]
            o = (c < rng.random(B)[:, None]).sum(-1)
            out[:, k, IDX["buy"]], out[:, k, IDX["sell"]] = buy, sell
            out[:, k, IDX["move"]], out[:, k, IDX["spread"]] = o // ns, o % ns
            prev = out[:, k]
        return out


def moves_half_ticks(tok: np.ndarray) -> np.ndarray:
    return tok[..., IDX["move"]] - MAX_MOVE


def n_params(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())

