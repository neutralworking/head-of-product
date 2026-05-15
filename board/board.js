(async function () {
  const $ = (sel) => document.querySelector(sel);

  const fmtDate = (iso) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toISOString().slice(0, 10);
    } catch {
      return iso;
    }
  };

  const fmtMoney = (n) => (n == null ? "—" : `£${n}`);

  let data;
  try {
    const res = await fetch("data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    $("#meta").textContent = `failed to load data.json: ${err.message}`;
    return;
  }

  $("#meta").textContent = `as of ${fmtDate(data.generated_at)}`;

  const projectsEl = $("#projects");
  const active = (data.projects || []).filter((p) =>
    ["now", "next", "later"].includes(p.tier)
  );
  active.sort((a, b) => {
    const order = { now: 0, next: 1, later: 2 };
    return (order[a.tier] ?? 9) - (order[b.tier] ?? 9);
  });

  if (!active.length) {
    projectsEl.innerHTML = `<div class="empty">no active projects</div>`;
  } else {
    for (const p of active) {
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <div class="row">
          <div class="name">${escapeHtml(p.name)}</div>
          <div>
            <span class="tier ${p.tier}">${p.tier}</span>
            ${p.revenue_status ? `<span class="revenue-pill ${p.revenue_status}">${p.revenue_status}</span>` : ""}
          </div>
        </div>
        <div class="last-touched"><strong>Last touched</strong>${fmtDate(p.last_touched)}</div>
        <div class="next-step"><strong>Next</strong>${escapeHtml(p.next_step || "—")}</div>
        <div class="blocker"><strong>Blocker</strong>${escapeHtml(p.blocker || "—")}</div>
      `;
      projectsEl.appendChild(card);
    }
  }

  const revenueBody = document.querySelector("#revenue tbody");
  const revenue = data.revenue || [];
  if (!revenue.length) {
    revenueBody.innerHTML = `<tr><td colspan="4" class="empty">no revenue rows yet</td></tr>`;
  } else {
    for (const r of revenue) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(r.project)}</td>
        <td class="num">${fmtMoney(r.monthly_gbp)}</td>
        <td>${escapeHtml(r.trajectory || "—")}</td>
        <td class="num">${fmtMoney(r.cost_gbp)}</td>
      `;
      revenueBody.appendChild(tr);
    }
  }

  const oppsEl = $("#opportunities");
  const opps = (data.opportunities || []).slice(0, 3);
  if (!opps.length) {
    oppsEl.innerHTML = `<li class="empty">no opportunities logged yet</li>`;
  } else {
    for (const o of opps) {
      const li = document.createElement("li");
      li.innerHTML = `
        <div><strong>${escapeHtml(o.opportunity)}</strong> <span class="tier ${o.fit || ""}">${escapeHtml(o.fit || "")}</span></div>
        <div class="next-step">${escapeHtml(o.next_step || "—")}</div>
      `;
      oppsEl.appendChild(li);
    }
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
