#!/usr/bin/env python3
"""Generate docs/workflow-{light,dark}.svg: an animated pipeline.

Two lanes (root cause, verify), flowing dashed connectors, a pulse that travels
each lane, and stages that brighten as the pulse passes.

Every animation is SEAMLESS by construction: each animated value starts and ends
the cycle on the same value, and dash offsets advance by exactly one dash period.
Nothing fades the whole frame out, which is what made the earlier attempt flicker.
"""
import html

W, H = 1200, 404
CYCLE = 7.0          # seconds for one pass of the pulse

DARK = dict(bg="#0d1117", card="#161b22", stroke="#30363d", text="#e6edf3",
            dim="#8b949e", faint="#6e7681", blue="#58a6ff", green="#3fb950",
            purple="#a371f7")
LIGHT = dict(bg="#ffffff", card="#f6f8fa", stroke="#d0d7de", text="#1f2328",
             dim="#59636e", faint="#818b98", blue="#0969da", green="#1a7f37",
             purple="#8250df")

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif"

LANE1_Y, LANE2_Y = 132, 300      # node top edge
NH = 56                          # node height

# (x, w, title, subtitle)
LANE1 = [
    (28, 150, "input", "PR · branch · trace"),
    (214, 150, "pr_context", "one normalized ctx"),
    (400, 140, "classify", "bugfix / feature"),
    (576, 170, "suspect", "rank the commits"),
    (782, 150, "risk score", "0 to 100"),
    (968, 204, "output", "JSON · HTML · MCP"),
]
LANE2 = [
    (28, 150, "proposed diff", "uncommitted"),
    (576, 170, "verify_fix", "the pre-commit gate"),
    (968, 204, "verdict", "complete / partial / risky"),
]


def esc(s):
    return html.escape(s, quote=False)


def node(x, y, w, title, sub, c, accent, peak):
    """A stage card whose border brightens as the pulse passes (peak = 0..1)."""
    lo, hi = max(0.0, peak - 0.05), min(1.0, peak + 0.09)
    # starts and ends on the base stroke, so the loop is seamless
    kt = "0;{:.4f};{:.4f};{:.4f};1".format(lo, peak, hi)
    vals = "{s};{s};{a};{s};{s}".format(s=c["stroke"], a=accent)
    return (
        '<g>'
        '<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill}" '
        'stroke="{s}" stroke-width="1.5">'
        '<animate attributeName="stroke" values="{vals}" keyTimes="{kt}" dur="{cy}s" '
        'repeatCount="indefinite"/>'
        '</rect>'
        '<text x="{cx}" y="{ty}" text-anchor="middle" font-family="{mono}" font-size="13.5" '
        'font-weight="600" fill="{tc}">{title}</text>'
        '<text x="{cx}" y="{sy}" text-anchor="middle" font-family="{sans}" font-size="11" '
        'fill="{dim}">{sub}</text>'
        '</g>'
    ).format(x=x, y=y, w=w, h=NH, fill=c["card"], s=c["stroke"], vals=vals, kt=kt,
             cy=CYCLE, cx=x + w / 2, ty=y + 24, sy=y + 41, mono=MONO, sans=SANS,
             tc=c["text"], dim=c["dim"], title=esc(title), sub=esc(sub))


def connector(x1, x2, y, c, color, delay):
    """A track with marching dashes plus a pulse that crosses it once per cycle."""
    period = 16  # dash 6 + gap 10
    dur = 1.1
    out = [
        # static rail
        '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{}" stroke-width="1.5" '
        'opacity="0.45"/>'.format(x1, y, x2, y, c["stroke"]),
        # marching dashes: offset advances exactly one period, so it is seamless
        '<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{col}" stroke-width="1.5" '
        'stroke-dasharray="6 10" opacity="0.55">'
        '<animate attributeName="stroke-dashoffset" from="0" to="-{p}" dur="{d}s" '
        'repeatCount="indefinite"/></line>'.format(x1=x1, y=y, x2=x2, col=color, p=period,
                                                   d=dur),
        # arrowhead
        '<path d="M {a} {b} L {c2} {y} L {a} {d2} z" fill="{col}" opacity="0.8"/>'.format(
            a=x2 - 7, b=y - 4, c2=x2, d2=y + 4, y=y, col=color),
    ]
    # The pulse: fades in and out at the ends so the wrap is invisible. Base cx/cy
    # and opacity="0" matter - before `begin` elapses an SVG element paints its base
    # attributes, and a circle with no cx/cy would flash at the origin.
    out.append(
        '<circle cx="{x1}" cy="{y}" r="4.5" fill="{col}" opacity="0">'
        '<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.12;0.85;1" '
        'dur="{cy}s" begin="{b}s" repeatCount="indefinite"/>'
        '<animate attributeName="cx" values="{x1};{x2}" dur="{cy}s" begin="{b}s" '
        'repeatCount="indefinite"/>'
        '<animate attributeName="cy" values="{y};{y}" dur="{cy}s" begin="{b}s" '
        'repeatCount="indefinite"/>'
        '</circle>'.format(col=color, cy=CYCLE, b=delay, x1=x1, x2=x2, y=y))
    return "".join(out)


def build(c, name):
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
         'height="{h}">'.format(w=W, h=H),
         '<rect width="{}" height="{}" fill="{}"/>'.format(W, H, c["bg"])]

    # header
    o.append('<text x="28" y="36" font-family="{}" font-size="11" font-weight="700" '
             'letter-spacing="1.5" fill="{}">DETERMINISTIC  ·  GIT ONLY  ·  READ-ONLY  ·  '
             'NO NETWORK</text>'.format(SANS, c["faint"]))

    # lane captions
    o.append('<text x="28" y="112" font-family="{}" font-size="11.5" font-weight="700" '
             'fill="{}">ROOT CAUSE <tspan fill="{}" font-weight="400">· what introduced '
             'this bug?</tspan></text>'.format(SANS, c["blue"], c["dim"]))
    o.append('<text x="28" y="280" font-family="{}" font-size="11.5" font-weight="700" '
             'fill="{}">VERIFY <tspan fill="{}" font-weight="400">· is my fix complete '
             'before I commit?</tspan></text>'.format(SANS, c["green"], c["dim"]))

    # lane 1 connectors + nodes
    ymid1 = LANE1_Y + NH / 2
    n = len(LANE1)
    for i in range(n - 1):
        x, w = LANE1[i][0], LANE1[i][1]
        nx = LANE1[i + 1][0]
        # pulse enters this segment proportionally through the cycle
        o.append(connector(x + w, nx, ymid1, c, c["blue"], round(i * CYCLE / n, 2)))
    for i, (x, w, t, s) in enumerate(LANE1):
        o.append(node(x, LANE1_Y, w, t, s, c, c["blue"], round((i + 0.35) / n, 3)))
    o.append('<text x="661" y="{}" text-anchor="middle" font-family="{}" font-size="10.5" '
             'fill="{}">evolution · intent · lifecycle · completeness</text>'.format(
                 LANE1_Y + NH + 20, SANS, c["faint"]))

    # lane 2 connectors + nodes
    ymid2 = LANE2_Y + NH / 2
    m = len(LANE2)
    for i in range(m - 1):
        x, w = LANE2[i][0], LANE2[i][1]
        nx = LANE2[i + 1][0]
        o.append(connector(x + w, nx, ymid2, c, c["green"], round(i * CYCLE / m, 2)))
    for i, (x, w, t, s) in enumerate(LANE2):
        accent = c["green"] if i < m - 1 else c["purple"]
        o.append(node(x, LANE2_Y, w, t, s, c, accent, round((i + 0.35) / m, 3)))
    o.append('<text x="661" y="{}" text-anchor="middle" font-family="{}" font-size="10.5" '
             'fill="{}">patch the untouched call sites it names, then re-run</text>'.format(
                 LANE2_Y + NH + 20, SANS, c["faint"]))

    o.append("</svg>")
    svg = "\n".join(o)
    path = "/Users/mac/culprit/docs/workflow-{}.svg".format(name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print("wrote", path, len(svg), "bytes")


build(DARK, "dark")
build(LIGHT, "light")
