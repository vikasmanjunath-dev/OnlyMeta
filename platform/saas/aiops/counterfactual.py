"""Counterfactual verification (P8b): did the action CAUSE the recovery, or was the node recovering anyway?

"Improved after the action" is not "improved because of it". This estimates what the metric would have done WITHOUT the action and asks
whether what actually happened is outside that:
  1. pre-action run: the samples since the problem began (back from the action until the metric was last normal);
  2. counterfactual: a robust (Theil-Sen) trend of that run extrapolated over the post-action window, never better than the learned
     normal and never worse than the worst value already seen (so no credit is claimed from an imagined deterioration);
  3. band: z standard errors of the difference of means (residual spread floored at the metric's own sigma, plus slope uncertainty);
  4. control: other nodes' same metric over the same window; if they improved too, the cause is fleet-wide, not the action.
Verdicts: caused | coincident | fleet_wide | inconclusive.  It is a statistical attribution under stated assumptions (see `assumptions`),
never a proof; a trend that stops or accelerates exactly at the action is beyond what a pre-action fit can see."""
from statistics import median
from typing import Optional

DEFAULTS = {"min_pre": 4, "min_post": 4, "z": 2.5, "run_slack_sigma": 3.0, "control_frac": 0.5, "max_pre_s": 90.0}
ASSUMPTIONS = ["higher is worse for this metric", "the pre-action trend would have continued (linear) absent the action", "other nodes are not affected by the action", "peers used as controls are not themselves being treated"]


def theil_sen(xs: list, ys: list) -> tuple:
    sl = [(ys[j] - ys[i]) / (xs[j] - xs[i]) for i in range(len(xs)) for j in range(i + 1, len(xs)) if xs[j] != xs[i]]
    b = median(sl) if sl else 0.0
    return b, median(y - b * x for x, y in zip(xs, ys))


def _mad_sigma(res: list) -> float:
    m = median(res)
    return 1.4826 * median(abs(r - m) for r in res)


def attribute(pre: list, post: list, floor: float, sigma: float, controls: Optional[list] = None, cfg: Optional[dict] = None) -> dict:
    """pre/post: [(t, value)] with t in seconds relative to the action (pre <= 0 < post). `floor` = learned normal, `sigma` = the metric's own sigma_eff.
    controls: [{"label", "pre": [...], "post": [...]}] for other nodes."""
    c = {**DEFAULTS, **(cfg or {})}
    base = {"method": "pre-action robust trend extrapolation with peer control", "assumptions": ASSUMPTIONS, "z": c["z"]}

    def out(v, why, **kw):
        return {**base, "verdict": v, "explain": why, **kw}
    pre = sorted(p for p in pre if p[0] >= -c["max_pre_s"])
    run = []
    for t, v in reversed(pre):                                     # the unbroken degraded run that ends at the action
        if v <= floor + c["run_slack_sigma"] * sigma:
            break
        run.append((t, v))
    run.reverse()
    post = sorted(post)
    if len(run) < c["min_pre"]:
        return out("inconclusive", f"only {len(run)} degraded sample(s) before the action (need {c['min_pre']}): too little history to say what the node would have done alone", pre_n=len(run), post_n=len(post))
    if len(post) < c["min_post"]:
        return out("inconclusive", f"only {len(post)} sample(s) after the action (need {c['min_post']})", pre_n=len(run), post_n=len(post))
    xs, ys = [t for t, _ in run], [v for _, v in run]
    b, a = theil_sen(xs, ys)
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    s_r = max(_mad_sigma(res), sigma)
    n, m = len(run), len(post)
    sxx = sum((x - sum(xs) / n) ** 2 for x in xs) or 1.0
    hi = max(ys)
    cf = [min(max(a + b * t, floor), hi) for t, _ in post]
    cf_mean, obs_mean = sum(cf) / m, sum(v for _, v in post) / m
    gap = sum(t for t, _ in post) / m - sum(xs) / n
    se = (s_r ** 2 / m + s_r ** 2 / n + (s_r / sxx ** 0.5 * gap) ** 2) ** 0.5
    band, effect = c["z"] * se, obs_mean - cf_mean
    lvl = median(ys[-3:])
    onset = next((t for (t, v), f in zip(post, cf) if v <= f - c["z"] * s_r), None)
    nums = dict(pre_n=n, post_n=m, slope_per_s=round(b, 4), counterfactual_mean=round(cf_mean, 2), observed_mean=round(obs_mean, 2), effect=round(effect, 2),
                band=round(band, 2), onset_lag_s=None if onset is None else round(onset, 1), level_at_action=round(lvl, 2))
    ctl = []
    for k in controls or []:
        pp, qq = [v for t, v in k.get("pre", []) if t >= -c["max_pre_s"]], [v for _, v in k.get("post", [])]
        if len(pp) >= 2 and len(qq) >= 2:
            ctl.append({"label": k.get("label"), "delta": round(sum(qq) / len(qq) - sum(pp) / len(pp), 2)})
    drop = lvl - obs_mean
    peers = [x for x in ctl if -x["delta"] >= max(c["control_frac"] * drop, 2 * sigma)]
    nums["controls"] = ctl
    if obs_mean >= lvl - 2 * sigma:
        return out("inconclusive", "the metric did not fall enough to attribute anything", **nums)
    if peers and drop > 0:
        return out("fleet_wide", f"other nodes ({', '.join(str(p['label']) for p in peers)}) improved by a similar amount over the same window: the cause is not specific to this action", **nums)
    if effect < -band:
        return out("caused", f"after the action the metric averaged {obs_mean:.1f}; its own pre-action trend predicted {cf_mean:.1f} (±{band:.1f}): {abs(effect):.1f} better than it would have been"
                             + (f", starting {onset:.0f} s after the action" if onset is not None else ""), **nums)
    return out("coincident", f"the metric fell, but its own pre-action trend ({b * 60:+.1f} per min) already predicted {cf_mean:.1f}; observed {obs_mean:.1f} is within ±{band:.1f} of that: the data does not credit the action", **nums)
