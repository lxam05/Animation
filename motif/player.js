// Motif browser player. Reads compiled tracks from #motif-data and draws them
// as SVG. World coordinates have y pointing UP, so every y is negated here.
(function () {
  const data = JSON.parse(document.getElementById("motif-data").textContent);
  const NS = "http://www.w3.org/2000/svg";
  const W = data.canvas.width, H = data.canvas.height;

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `${-W / 2} ${-H / 2} ${W} ${H}`);
  const bg = el("rect", { x: -W / 2, y: -H / 2, width: W, height: H, fill: data.canvas.background });
  svg.appendChild(bg);
  const defs = el("defs");
  svg.appendChild(defs);
  document.getElementById("stage").appendChild(svg);

  function el(tag, attrs = {}) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // ---------------------------------------------------------------- easing
  const EASE = {
    linear: (u) => u,
    smooth: (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2),
    in_out: (u) => (u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2),
    in: (u) => u * u * u,
    out: (u) => 1 - Math.pow(1 - u, 3),
  };

  function hex(c) {
    const n = parseInt(c.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function lerp(a, b, u) {
    if (typeof a === "number") return a + (b - a) * u;
    if (typeof a === "string" && a[0] === "#" && typeof b === "string") {
      const x = hex(a), y = hex(b);
      return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * u).toString(16).padStart(2, "0")).join("");
    }
    if (Array.isArray(a)) return a.map((v, i) => lerp(v, b[i], u));
    return u < 1 ? a : b; // strings, null: snap
  }

  // Value of every property of object `o` at time t.
  function stateAt(o, t) {
    const s = Object.assign({}, o.init);
    const done = {};
    for (const [p, t0, t1, a, b, e] of o.segs) {
      if (done[p] || t < t0) { if (t < t0) done[p] = true; continue; }
      if (t >= t1) s[p] = b;
      else { s[p] = lerp(a, b, EASE[e]((t - t0) / (t1 - t0))); done[p] = true; }
    }
    return s;
  }

  // -------------------------------------------------------------- build DOM
  const clamp = (v) => Math.max(0, Math.min(1, v));
  const nodes = data.objects.map((o, idx) => {
    const g = el("g");
    svg.appendChild(g);
    const n = { o, g };
    const dash = { "pathLength": 1, "stroke-dasharray": "1 1", fill: "none" };
    switch (o.type) {
      case "circle": case "dot": n.shape = el("circle", { pathLength: 1, "stroke-dasharray": "1 1" }); break;
      case "rect": n.shape = el("rect", { pathLength: 1, "stroke-dasharray": "1 1" }); break;
      case "line": n.shape = el("line", dash); break;
      case "arrow": n.shape = el("line", dash); n.head = el("polygon"); g.appendChild(n.head); break;
      case "text":
        n.shape = el("text", { "text-anchor": "middle", "dominant-baseline": "central",
          "font-family": { sans: "system-ui, Helvetica, Arial, sans-serif", serif: "Georgia, serif", mono: "ui-monospace, Menlo, monospace" }[o.geom.font],
          "font-weight": o.geom.weight });
        break;
      case "axes":
        n.shape = el("g", { fill: "none" });
        n.lines = o.geom.lines.map(([x1, y1, x2, y2]) => {
          const l = el("line", Object.assign({ x1, y1: -y1, x2, y2: -y2 }, dash));
          n.shape.appendChild(l); return l;
        });
        break;
      case "graph": {
        const [cx, cy, cw, ch] = o.geom.clip;
        const id = "clip" + idx;
        const cp = el("clipPath", { id });
        cp.appendChild(el("rect", { x: cx, y: -(cy + ch), width: cw, height: ch }));
        defs.appendChild(cp);
        n.shape = el("polyline", Object.assign({ "clip-path": `url(#${id})`, "stroke-linejoin": "round", "stroke-linecap": "round" }, dash));
        break;
      }
    }
    g.insertBefore(n.shape, g.firstChild);
    return n;
  });

  function setStroke(e, s) {
    e.setAttribute("stroke", s.stroke || "none");
    e.setAttribute("stroke-width", s.stroke_width || 0);
    e.setAttribute("stroke-dashoffset", 1 - s.draw);
  }

  function draw(t) {
    for (const n of nodes) {
      const { o, g, shape } = n;
      const s = stateAt(o, t);
      if (s.opacity <= 0.001) { g.setAttribute("display", "none"); continue; }
      g.removeAttribute("display");
      g.setAttribute("opacity", s.opacity);
      const [ox, oy] = o.geom.origin, [px, py] = o.pivot;
      const dx = s.x - ox, dy = s.y - oy;
      g.setAttribute("transform",
        `translate(${dx} ${-dy}) translate(${px} ${-py}) rotate(${-s.rotation}) scale(${s.scale}) translate(${-px} ${py})`);
      const fillAlpha = clamp((s.draw - 0.4) / 0.6);
      switch (o.type) {
        case "circle": case "dot":
          shape.setAttribute("r", s.r);
          shape.setAttribute("fill", s.fill || "none");
          shape.setAttribute("fill-opacity", fillAlpha);
          setStroke(shape, s);
          break;
        case "rect":
          shape.setAttribute("x", -s.w / 2); shape.setAttribute("y", -s.h / 2);
          shape.setAttribute("width", s.w); shape.setAttribute("height", s.h);
          shape.setAttribute("rx", s.corner);
          shape.setAttribute("fill", s.fill || "none");
          shape.setAttribute("fill-opacity", fillAlpha);
          setStroke(shape, s);
          break;
        case "line": case "arrow": {
          const [x1, y1] = s.start, [x2, y2] = s.end;
          let ex = x2, ey = y2;
          if (o.type === "arrow") {
            const L = Math.hypot(x2 - x1, y2 - y1) || 1, ux = (x2 - x1) / L, uy = (y2 - y1) / L;
            const h = Math.min(o.geom.head, L * 0.5), w = h * 0.6;
            ex = x2 - ux * h * 0.9; ey = y2 - uy * h * 0.9; // stop the shaft under the head
            const bx = x2 - ux * h, by = y2 - uy * h;
            const pts = [[x2, y2], [bx - uy * w, by + ux * w], [bx + uy * w, by - ux * w]];
            n.head.setAttribute("points", pts.map(([a, b]) => `${a},${-b}`).join(" "));
            n.head.setAttribute("fill", s.stroke || "#fff");
            n.head.setAttribute("opacity", clamp((s.draw - 0.8) * 5));
          }
          shape.setAttribute("x1", x1); shape.setAttribute("y1", -y1);
          shape.setAttribute("x2", ex); shape.setAttribute("y2", -ey);
          shape.setAttribute("stroke-linecap", "round");
          setStroke(shape, s);
          break;
        }
        case "text":
          shape.textContent = s.text;
          shape.setAttribute("font-size", s.size);
          shape.setAttribute("fill", s.fill || "#fff");
          break;
        case "axes":
          for (const l of n.lines) setStroke(l, s);
          break;
        case "graph":
          shape.setAttribute("points", s.points.map(([a, b]) => `${a},${-b}`).join(" "));
          setStroke(shape, s);
          break;
      }
    }
  }

  // --------------------------------------------------------------- playback
  const dur = Math.max(data.duration, 0.01) + 1; // hold the last frame for 1s
  const btn = document.getElementById("play"), scrub = document.getElementById("scrub"),
    label = document.getElementById("time");
  let t = 0, playing = true, last = null;

  function show(time) {
    t = Math.max(0, Math.min(dur, time));
    draw(t);
    scrub.value = Math.round((t / dur) * 1000);
    label.textContent = `${t.toFixed(2)}s / ${data.duration.toFixed(2)}s`;
  }
  function frame(now) {
    if (playing) {
      if (last !== null) show(t + (now - last) / 1000);
      if (t >= dur) t = 0; // loop
    }
    last = now;
    requestAnimationFrame(frame);
  }
  btn.onclick = () => { playing = !playing; btn.textContent = playing ? "Pause" : "Play"; };
  document.getElementById("restart").onclick = () => show(0);
  scrub.oninput = () => { playing = false; btn.textContent = "Play"; show((scrub.value / 1000) * dur); };
  document.addEventListener("keydown", (e) => { if (e.code === "Space") { e.preventDefault(); btn.click(); } });

  // Hook for headless frame export (Playwright): motif.seek(1.5) then screenshot.
  window.motif = { seek: (s) => { playing = false; show(s); }, duration: data.duration, fps: data.canvas.fps };
  show(0);
  requestAnimationFrame(frame);
})();
