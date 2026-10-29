"""Quick matplotlib preview of rendered line views."""
import json, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

data = json.load(open(sys.argv[1]))
views = [(a, v, d) for a, arm in data.items() for v, d in arm["views"].items()]
fig, axes = plt.subplots(1, len(views), figsize=(8 * len(views), 9), facecolor="#123a7a")
axes = [axes] if len(views) == 1 else axes
for ax, (arm, view, d) in zip(axes, views):
    ax.set_facecolor("#123a7a")
    for name, color, width in (("hidden", "#5f83c4", 0.3), ("crease", "white", 0.4), ("silhouette", "white", 0.9)):
        ax.add_collection(LineCollection(d["lines"][name], colors=color, linewidths=width))
    for jname, (x, y) in d["joints_2d"].items():
        ax.plot(x, y, "o", color="orange", ms=4); ax.text(x, y, jname, color="orange", fontsize=7)
    (x0, y0), (x1, y1) = d["bounds"]
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal"); ax.set_title(f"{arm} {view}", color="white")
    ax.axis("off")
plt.savefig(sys.argv[2], dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
