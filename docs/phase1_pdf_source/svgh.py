PAL = ["#0D9488", "#7C3AED", "#E11D48", "#2563EB", "#16A34A", "#F59E0B", "#64748B", "#0B1F3A", "#B91C1C", "#047857"]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def defs():
    out = "<defs>"
    for c in PAL:
        out += (f'<marker id="m{c[1:]}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="7" markerHeight="7" '
                f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>')
    out += "</defs>"
    return out


def svg(w, h, body, extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%" {extra}>'
            + defs() + body + "</svg>")


def T(x, y, s, size=12, fill="#1F2937", w=500, anchor="start", extra=""):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{w}" '
            f'text-anchor="{anchor}" {extra}>{esc(s)}</text>')


def R(x, y, w, h, fill, stroke="none", rx=8, sw=1.5, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'


def box(x, y, w, h, fill, stroke, title, sub=None, tc="#0B1F3A", sc="#475569", ts=12, ss=10, rx=8, dash=False):
    d = 'stroke-dasharray="5 3"' if dash else ""
    out = R(x, y, w, h, fill, stroke, rx, 1.6, d)
    cx = x + w / 2
    if sub:
        out += T(cx, y + h / 2 - 2, title, ts, tc, 700, "middle")
        out += T(cx, y + h / 2 + 12, sub, ss, sc, 500, "middle")
    else:
        out += T(cx, y + h / 2 + ts / 3, title, ts, tc, 700, "middle")
    return out


def line(pts, color, dashed=False, sw=2.2, arrow=True, both=False):
    p = " ".join(f"{a},{b}" for a, b in pts)
    d = 'stroke-dasharray="6 4"' if dashed else ""
    m = f'marker-end="url(#m{color[1:]})"' if arrow else ""
    if both:
        m += f' marker-start="url(#m{color[1:]})"'
    return f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{sw}" {d} {m} stroke-linejoin="round"/>'


def badge(x, y, n, color="#0B1F3A", r=10):
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>'
            + T(x, y + 4, str(n), 11, "#fff", 800, "middle"))


def spark(vals, w, h, color, hl=None, fill=True, ymin=None, ymax=None, pad=4):
    lo = min(vals) if ymin is None else ymin
    hi = max(vals) if ymax is None else ymax
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = pad + i * (w - 2 * pad) / (n - 1)
        y = h - pad - (v - lo) / (hi - lo + 1e-9) * (h - 2 * pad)
        pts.append((round(x, 1), round(y, 1)))
    s = ""
    if fill:
        poly = " ".join(f"{a},{b}" for a, b in pts) + f" {pts[-1][0]},{h - pad} {pts[0][0]},{h - pad}"
        s += f'<polygon points="{poly}" fill="{color}" opacity="0.15"/>'
    s += f'<polyline points="{" ".join(f"{a},{b}" for a, b in pts)}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
    if hl is not None:
        for i in (hl if isinstance(hl, (list, tuple)) else [hl]):
            s += f'<circle cx="{pts[i][0]}" cy="{pts[i][1]}" r="3.6" fill="#E11D48"/>'
    return s
