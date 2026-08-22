// ---------------------------------------------------------------------------
// Profile analytics.
//
// These four panels were a band in the middle of the dashboard, which put four
// plots in front of the two lists people come back to that page to act on.
// They are their own page now, reached by the Analytics button on the
// dashboard's profile header.
//
// One request, the same /api/dashboard the dashboard itself reads. Nothing
// here is computed that the payload does not already carry, and nothing is
// modelled or projected: every number drawn is one the server counted.
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
    const esc = window.escapeHtml;

    let dashboard;
    let proposals = [];
    try {
        // A 401 sends the visitor to the login page from inside window.api,
        // the same as everywhere else, so the signed-out case needs nothing
        // here.
        //
        // Together rather than one after the other: they do not depend on
        // each other, and this page is two round trips deep before it can draw
        // anything.
        const [dash, list] = await Promise.all([
            window.api('/api/dashboard'),
            // The ring's segments open into this. A failure here is not worth
            // failing the page over -- the charts still draw, and the
            // segments say the list is unavailable when opened.
            window.api('/api/proposals').catch(() => null),
        ]);
        dashboard = dash;
        proposals = (list && list.proposals) || [];
    } catch (error) {
        const failed = document.getElementById('analyticsNote');
        if (failed) {
            failed.textContent = error.message
                || 'Could not load your numbers. Try again in a moment.';
            failed.classList.add('is-error');
        }
        return;
    }

    // Says what the window is once, rather than each panel repeating it.
    const note = document.getElementById('analyticsNote');
    if (note) {
        note.textContent = dashboard.needs_onboarding
            ? 'Your profile is not finished, so most of this has nothing to '
              + 'count yet.'
            : 'Private to you. Nobody else sees these numbers.';
    }

    // --- The panels ------------------------------------------------------
    // Three of the four are rows of HTML: a label, a bar with a width, and a
    // value. Only the views plot is a drawing, and it is inline SVG rather
    // than a charting library -- one small fixed shape, and what follows is
    // smaller than the download of anything that would draw it for us. It also
    // means the marks are styled by the same stylesheet as everything else, so
    // they follow the theme without being told about it.
    //
    // The plot is drawn in its own coordinate space and scaled by the viewBox,
    // so nothing here has to measure the panel or redraw on resize.


    function svgEl(name, attrs) {
        const el = document.createElementNS('http://www.w3.org/2000/svg', name);
        Object.entries(attrs || {}).forEach(([k, v]) => el.setAttribute(k, v));
        return el;
    }

    /** A y-axis top that is a round number at or above the data's peak. */
    function niceCeiling(max) {
        if (max <= 4) return Math.max(1, max);
        const step = 10 ** Math.floor(Math.log10(max));
        return Math.ceil(max / (step / 2)) * (step / 2);
    }

    function shortDate(iso) {
        const [y, m, d] = iso.split('-').map(Number);
        return new Date(y, m - 1, d).toLocaleDateString('en-US', {
            month: 'short', day: 'numeric',
        });
    }

    /** One tooltip, moved and relabelled, rather than one per mark. */
    function attachTooltip(host) {
        const tip = document.createElement('div');
        tip.className = 'chart-tooltip';
        host.style.position = 'relative';
        host.appendChild(tip);
        return {
            show(text, x, y) {
                tip.textContent = text;
                tip.classList.add('on');
                // Measured after the text is in, so a long label is not
                // centered on the width of the previous one.
                tip.style.left = `${Math.max(0, x - tip.offsetWidth / 2)}px`;
                tip.style.top = `${y - tip.offsetHeight - 8}px`;
            },
            hide() { tip.classList.remove('on'); },
        };
    }

    function emptyChart(host, message) {
        host.innerHTML = '';
        const p = document.createElement('p');
        p.className = 'chart-empty';
        p.textContent = message;
        host.appendChild(p);
    }

    // --- Profile views, daily --------------------------------------------
    function renderViewsChart() {
        const host = document.getElementById('viewsChart');
        const total = document.getElementById('viewsPanelTotal');
        if (!host) return;

        const stats = (dashboard && dashboard.stats) || {};
        const series = stats.profile_views_series || [];
        const sum = series.reduce((n, d) => n + d.count, 0);
        if (total) total.textContent = String(sum);

        // Against the same length of window immediately before this one. Held
        // back entirely when there is nothing to compare with: "up 100% from
        // zero" is a sentence that says nothing.
        const delta = document.getElementById('viewsPanelDelta');
        if (delta) {
            const prior = stats.profile_views_prior;
            if (typeof prior !== 'number' || (prior === 0 && sum === 0)) {
                delta.textContent = '';
            } else if (prior === 0) {
                delta.textContent = 'First views in this window';
            } else {
                const change = Math.round(((sum - prior) / prior) * 100);
                const up = change > 0;
                delta.className = `panel-delta${
                    change === 0 ? '' : (up ? ' is-up' : ' is-down')}`;
                delta.innerHTML = change === 0
                    ? '<b>No change</b> vs. prior 30 days'
                    : `<b>${up ? '▲' : '▼'} ${Math.abs(change)}%</b> vs. prior 30 days`;
            }
        }

        if (series.length === 0) {
            emptyChart(host, 'No views recorded yet. The count starts when '
                + 'someone opens your public profile.');
            return;
        }

        // Measured, not fixed. The panel beside this one is what decides how
        // tall the row is, so a plot with a fixed aspect either floats in a
        // stripe of dead space or overflows. Drawing in the host's own pixels
        // -- one user unit to one CSS pixel -- also means nothing here is
        // scaled by the viewBox, so the axis type is the size it says it is
        // rather than the size the panel happens to make it.
        //
        // clientWidth/Height, and only once the box has one: this runs before
        // the flex row has settled, and measuring then returned the CSS
        // min-height rather than the height the panel actually gives it. The
        // observer below calls back with the real size and every size after.
        const W = host.clientWidth;
        const H = host.clientHeight;
        if (W < 120 || H < 60) return;
        const pad = { top: 10, right: 8, bottom: 20, left: 26 };
        const plotW = W - pad.left - pad.right;
        const plotH = H - pad.top - pad.bottom;
        const top = niceCeiling(Math.max(...series.map((d) => d.count)));
        const x = (i) => pad.left + (series.length === 1
            ? plotW / 2
            : (i / (series.length - 1)) * plotW);
        const y = (v) => pad.top + plotH - (v / top) * plotH;

        host.innerHTML = '';
        const svg = svgEl('svg', {
            viewBox: `0 0 ${W} ${H}`,
            class: 'plot',
            role: 'img',
            'aria-label': `Profile views per day over the last ${series.length}`
                + ` days. ${sum} in total.`,
        });

        // Gridlines and their ticks. Whole numbers while the peak is small --
        // half of three is not a number of views -- and nothing / half / all
        // once it is big enough for that to be crowded.
        const ticks = top <= 4
            ? Array.from({ length: top + 1 }, (_, i) => i)
            : [0, top / 2, top];
        ticks.forEach((v) => {
            svg.appendChild(svgEl('line', {
                class: 'grid-line',
                x1: pad.left, x2: W - pad.right, y1: y(v), y2: y(v),
            }));
            const label = svgEl('text', {
                class: 'axis-text', x: pad.left - 5, y: y(v) + 3,
                'text-anchor': 'end',
            });
            label.textContent = String(Math.round(v));
            svg.appendChild(label);
        });

        const line = series.map((d, i) => `${x(i)},${y(d.count)}`).join(' L');
        svg.appendChild(svgEl('path', {
            class: 'series-area',
            d: `M${x(0)},${y(0)} L${line} L${x(series.length - 1)},${y(0)} Z`,
        }));
        svg.appendChild(svgEl('path', { class: 'series-line', d: `M${line}` }));

        // The end of the series is the point the reader is here for, so it is
        // the one that gets a marker and a label.
        const last = series[series.length - 1];
        svg.appendChild(svgEl('circle', {
            class: 'series-end', cx: x(series.length - 1), cy: y(last.count), r: 3.5,
        }));

        // First and last dates only. A tick under all thirty would be a wall.
        [[0, 'start'], [series.length - 1, 'end']].forEach(([i, anchor]) => {
            const t = svgEl('text', {
                class: 'axis-text', x: x(i), y: H - 5, 'text-anchor': anchor,
            });
            t.textContent = shortDate(series[i].date);
            svg.appendChild(t);
        });

        // The hover layer. One hit column per day, each the full height of the
        // plot -- the 2px line itself is far too thin to aim at.
        const tip = attachTooltip(host);
        const band = plotW / Math.max(1, series.length - 1);
        series.forEach((d, i) => {
            const g = svgEl('g', {});
            g.appendChild(svgEl('rect', {
                class: 'hit',
                x: x(i) - band / 2, y: pad.top, width: band, height: plotH,
            }));
            g.appendChild(svgEl('line', {
                class: 'crosshair', x1: x(i), x2: x(i), y1: pad.top, y2: pad.top + plotH,
            }));
            g.appendChild(svgEl('circle', {
                class: 'hover-dot', cx: x(i), cy: y(d.count), r: 3.5,
            }));
            g.addEventListener('pointermove', () => {
                tip.show(
                    `${shortDate(d.date)} · ${d.count} view${d.count === 1 ? '' : 's'}`,
                    x(i), y(d.count),
                );
            });
            g.addEventListener('pointerleave', tip.hide);
            svg.appendChild(g);
        });

        host.appendChild(svg);

        const table = document.getElementById('viewsTable');
        if (table) {
            table.innerHTML = `
                <table>
                    <thead><tr><th>Day</th><th class="num">Views</th></tr></thead>
                    <tbody>${series.map((d) => `
                        <tr><td>${esc(shortDate(d.date))}</td>
                            <td class="num">${d.count}</td></tr>`).join('')}
                    </tbody>
                </table>`;
        }
    }

    // --- Strongest matches ------------------------------------------------
    // HTML rows rather than SVG. An SVG's text scales with its viewBox, so the
    // same 10px label rendered at 15px in the wide panel and at 8px in the
    // narrow one -- the same class, two different sizes on one screen. A bar
    // is a div with a width, and a label is text; neither needs a drawing
    // surface. Only the views chart below is a real plot, and it keeps its
    // SVG because a path is the thing it actually needs.
    function bar(pct, cls) {
        const width = pct > 0 ? `${Math.max(1.5, pct)}%` : '0';
        return `<span class="bar-track"><span class="bar${
            cls ? ` ${cls}` : ''}" style="width:${width}"></span></span>`;
    }

    function renderMatchChart() {
        const host = document.getElementById('matchChart');
        if (!host) return;

        const matches = (dashboard && dashboard.top_matches) || [];
        if (matches.length === 0) {
            emptyChart(host, dashboard && dashboard.needs_onboarding
                ? 'Finish your profile and the matcher can start scoring.'
                : 'No matches scored yet. More needs and offers widen the search.');
            return;
        }

        // The scale is 0-100 whatever the scores happen to be, so a 60 looks
        // like a 60 rather than filling the panel because it is the best one
        // on the list.
        host.innerHTML = `
            <div class="rows">
                ${matches.map((m) => {
                    const score = Math.max(0, Math.min(100, Number(m.match_score) || 0));
                    const mutual = Boolean(m.match_detail && m.match_detail.mutual);
                    return `
                        <div class="row">
                            <span class="row-label">
                                ${esc(m.name || 'Unnamed')}
                                ${mutual ? '<b class="row-flag">2-way</b>' : ''}
                            </span>
                            ${bar(score)}
                            <span class="row-value">${score}</span>
                        </div>`;
                }).join('')}
            </div>
            <div class="rows-scale">
                <span class="scale-ticks"><span>0</span><span>50</span><span>100</span></span>
            </div>`;

        const table = document.getElementById('matchTable');
        if (table) {
            table.innerHTML = `
                <table>
                    <thead><tr><th>Organization</th><th>Direction</th>
                        <th class="num">Score</th></tr></thead>
                    <tbody>${matches.map((m) => `
                        <tr><td>${esc(m.name || 'Unnamed')}</td>
                            <td>${m.match_detail && m.match_detail.mutual
                                ? 'Two-way' : 'One-way'}</td>
                            <td class="num">${Number(m.match_score) || 0}</td></tr>`).join('')}
                    </tbody>
                </table>`;
        }
    }

    // --- Pipeline ---------------------------------------------------------
    // A donut, extruded. Each partnership is in exactly one of four states, so
    // the four are parts of one whole and a ring is a fair way to draw them.
    //
    // On the "3D": the plan is a true circle, never an ellipse. Squashing it
    // into perspective is what makes a 3D pie lie -- the slices nearest the
    // viewer gain apparent area and the ones at the back lose it, so two equal
    // values stop looking equal. The depth here is a straight downward
    // extrusion of the same circle: every segment is offset by the same few
    // pixels in the same direction, so the arc each one subtends is exactly
    // its share and nothing is foreshortened.
    //
    // Four segments is inside the limit for reading a ring at a glance, and
    // the exact counts are in the legend beside it, because a ring answers
    // "roughly how is this split" and never "how many".
    function renderPipelineChart() {
        const host = document.getElementById('pipelineChart');
        if (!host) return;

        const s = (dashboard && dashboard.stats) || {};
        // Ordered, and the order is the point: a proposal moves down this list
        // as it goes. That is what makes the color an ordinal ramp -- one hue,
        // getting darker -- rather than four identities.
        const stages = [
            { label: 'Sent, waiting', value: s.sent_pending || 0, step: 1 },
            { label: 'Waiting on you', value: s.awaiting_you || 0, step: 2 },
            { label: 'Agreed', value: s.agreed || 0, step: 3 },
            { label: 'Completed', value: s.completed || 0, step: 4 },
        ];
        const total = stages.reduce((n, st) => n + st.value, 0);

        if (total === 0) {
            emptyChart(host, 'Nothing in flight. A proposal you send, or one '
                + 'sent to you, starts here.');
            return;
        }

        const SIZE = 200;
        const c = SIZE / 2;
        const rOuter = 84;
        const rInner = 52;
        const DEPTH = 11;          // How far the ring is extruded downward.
        const GAP = 0.022;         // Radians of surface between segments.

        const point = (r, a) => [c + r * Math.cos(a), c + r * Math.sin(a)];

        /** A slice of an annulus between two radii, as a closed path. */
        function segmentBand(from, to, inner, outer, dy = 0) {
            const large = to - from > Math.PI ? 1 : 0;
            const [ox1, oy1] = point(outer, from);
            const [ox2, oy2] = point(outer, to);
            const [ix2, iy2] = point(inner, to);
            const [ix1, iy1] = point(inner, from);
            return `M${ox1},${oy1 + dy}`
                + ` A${outer},${outer} 0 ${large} 1 ${ox2},${oy2 + dy}`
                + ` L${ix2},${iy2 + dy}`
                + ` A${inner},${inner} 0 ${large} 0 ${ix1},${iy1 + dy}`
                + ' Z';
        }

        /** One segment of the ring itself. */
        const segment = (from, to, dy) =>
            segmentBand(from, to, rInner, rOuter, dy);

        // Starts at the top and runs clockwise, which is where a reader's eye
        // starts and the direction they expect a sequence to run.
        let angle = -Math.PI / 2;
        const arcs = stages.map((st) => {
            const sweep = (st.value / total) * Math.PI * 2;
            const from = angle + (st.value ? GAP / 2 : 0);
            const to = angle + sweep - (st.value ? GAP / 2 : 0);
            // The bounds without the gap taken out. The gap is a piece of
            // drawing, not a piece of the data, and a pointer over it belongs
            // to one of the two slices either side rather than to neither.
            const hitFrom = angle;
            const hitTo = angle + sweep;
            angle += sweep;
            return {
                ...st, from, to, hitFrom, hitTo,
                drawn: st.value > 0 && to > from,
            };
        });

        host.innerHTML = '';
        const svg = svgEl('svg', {
            viewBox: `0 0 ${SIZE} ${SIZE + DEPTH}`,
            class: 'donut',
            role: 'img',
            'aria-label': `Partnerships by state, ${total} in total: ${stages
                .map((st) => `${st.label}, ${st.value}`).join('; ')}.`,
        });

        // Wall and face are one group per segment so they move together, and
        // every wall is drawn before every face -- one segment's wall must
        // never sit on top of its neighbour's face, which is what happens if
        // each pair is grouped in the document and the groups are stacked.
        //
        // So: two passes over the same arcs, and the hover transform is
        // applied to the two halves separately rather than to a wrapper.
        const walls = svgEl('g', { class: 'donut-walls' });
        const faces = svgEl('g', { class: 'donut-faces' });
        const drawn = arcs.filter((a) => a.drawn);

        drawn.forEach((a) => {
            // The direction this segment points, from the middle outwards.
            // The lift below rides along it, so a slice separates from its
            // neighbours rather than sliding across them.
            const mid = (a.from + a.to) / 2;
            a.dx = Math.cos(mid).toFixed(3);
            a.dy = Math.sin(mid).toFixed(3);

            a.wall = svgEl('path', {
                class: `donut-wall step-${a.step}`,
                d: segment(a.from, a.to, DEPTH),
                style: `--dx:${a.dx};--dy:${a.dy}`,
            });
            walls.appendChild(a.wall);
        });

        drawn.forEach((a) => {
            a.face = svgEl('path', {
                class: `donut-face step-${a.step}`,
                d: segment(a.from, a.to, 0),
                style: `--dx:${a.dx};--dy:${a.dy}`,
            });
            faces.appendChild(a.face);
        });

        svg.appendChild(walls);
        svg.appendChild(faces);

        // The hit layer, on top and never moved.
        //
        // Hovering used to be bound to the face itself, which lifts out from
        // under the pointer the moment it is hovered -- so the pointer left,
        // the face dropped back, the pointer was over it again, and the slice
        // flickered between the two states for as long as it was held near an
        // edge.
        //
        // These are the shapes the pointer is actually tested against: they
        // stay where they are whatever the face does, they carry the gaps back
        // in so neighbours touch and there is no dead band between two slices,
        // and they run wider than the ring on both sides so the whole lifted
        // position stays inside the region that lifted it.
        const hits = svgEl('g', { class: 'donut-hits' });
        drawn.forEach((a) => {
            a.hit = svgEl('path', {
                class: 'donut-hit',
                d: segmentBand(a.hitFrom, a.hitTo, rInner - 8, rOuter + 14),
            });
            hits.appendChild(a.hit);
        });
        svg.appendChild(hits);

        // The total, in the hole. A ring with an empty middle spends its best
        // space on nothing.
        const value = svgEl('text', {
            class: 'donut-total', x: c, y: c + 2, 'text-anchor': 'middle',
        });
        value.textContent = String(total);
        svg.appendChild(value);
        const caption = svgEl('text', {
            class: 'donut-caption', x: c, y: c + 18, 'text-anchor': 'middle',
        });
        caption.textContent = total === 1 ? 'partnership' : 'in total';
        svg.appendChild(caption);

        host.appendChild(svg);

        // The legend carries identity and the exact counts, so neither depends
        // on telling two steps of one hue apart by eye.
        const legend = document.createElement('ul');
        legend.className = 'donut-legend';
        legend.innerHTML = stages.map((st) => `
            <li data-step="${st.step}"${st.value ? '' : ' class="is-empty"'}>
                <span class="key step-${st.step}"></span>
                <span class="key-label">${esc(st.label)}</span>
                <span class="key-value">${st.value}</span>
            </li>`).join('');
        host.appendChild(legend);

        // --- The lift ------------------------------------------------------
        // Hovering a segment raises its face off its own wall, which is what
        // makes it read as rising rather than sliding: the wall stays on the
        // ground and only steps outward, so the gap between the two grows and
        // the slice looks taller. Both halves move along the same outward
        // direction, so the slice separates from its neighbours instead of
        // crossing them.
        //
        // Driven from the group, not from :hover on each path -- a pointer
        // between two segments would otherwise light neither, and the legend
        // row has to be able to raise the slice too.
        const tip = attachTooltip(host);
        const legendRows = [...legend.querySelectorAll('li')];

        function lift(step) {
            svg.classList.toggle('is-lifting', step !== null);
            drawn.forEach((a) => {
                const on = a.step === step;
                a.face.classList.toggle('is-lifted', on);
                a.wall.classList.toggle('is-lifted', on);
            });
            legendRows.forEach((li) => {
                li.classList.toggle('is-on', Number(li.dataset.step) === step);
            });
        }

        function bind(el, a) {
            el.addEventListener('click', () => openStage(a));
            // A legend row is a control now, so it answers the keyboard too.
            if (el.tagName === 'LI') {
                el.tabIndex = 0;
                el.addEventListener('keydown', (e) => {
                    if (e.key !== 'Enter' && e.key !== ' ') return;
                    e.preventDefault();
                    openStage(a);
                });
                el.addEventListener('focus', () => lift(a.step));
                el.addEventListener('blur', () => { lift(null); tip.hide(); });
            }
            el.addEventListener('pointerenter', () => {
                lift(a.step);
                const share = Math.round((a.value / total) * 100);
                const box = host.getBoundingClientRect();
                const svgBox = svg.getBoundingClientRect();
                // Placed at the segment's own middle, in the host's pixels.
                const scale = svgBox.width / SIZE;
                const mid = (a.from + a.to) / 2;
                // Anchored on the ring's outer edge rather than the middle of
                // the band, so the label clears the slice it is naming instead
                // of sitting on top of it.
                const r = rOuter;
                tip.show(
                    `${a.label} · ${a.value} (${share}%)`,
                    svgBox.left - box.left + (c + r * Math.cos(mid)) * scale,
                    svgBox.top - box.top + (c + r * Math.sin(mid)) * scale,
                );
            });
            el.addEventListener('pointerleave', () => {
                lift(null);
                tip.hide();
            });
        }

        drawn.forEach((a) => {
            bind(a.hit, a);
            const row = legendRows.find((li) => Number(li.dataset.step) === a.step);
            if (row) bind(row, a);
        });
    }

    // --- Profile coverage -------------------------------------------------
    // Three ratios against a known limit, which is a meter rather than a
    // chart. The track is a step of the fill's own ramp so the state reads
    // across the whole bar, not only the filled part.
    function renderCoverage() {
        const host = document.getElementById('coverageMeters');
        if (!host) return;

        const s = (dashboard && dashboard.stats) || {};
        const org = (dashboard && dashboard.organization) || {};
        const focus = (org.focus_areas || []).length;
        const rows = [
            { label: 'Needs listed', value: s.needs_count || 0, of: s.category_total },
            { label: 'Offers listed', value: s.offers_count || 0, of: s.category_total },
            { label: 'Causes listed', value: focus, of: s.focus_total },
            // The two totals ride along on the payload rather than being
            // written here: the vocabulary's size lives in categories.py, and
            // a 33 typed into a script is a number that goes stale the first
            // time a category is added.
        ].filter((r) => r.of);

        if (rows.length === 0) {
            emptyChart(host, 'Coverage appears once the category list has loaded.');
            return;
        }

        host.innerHTML = rows.map((r) => `
            <div class="meter">
                <div class="meter-label">
                    <span>${esc(r.label)}</span>
                    <span><b>${r.value}</b> / ${r.of}</span>
                </div>
                ${bar((r.value / r.of) * 100)}
            </div>`).join('');

        // Says what the meters are for. Without it they are three bars that
        // look like a score.
        const note = document.createElement('p');
        note.className = 'meter-note';
        note.textContent = (s.needs_count || 0) === 0 || (s.offers_count || 0) === 0
            ? 'Scored on both directions — nothing on one side can only ever '
              + 'half-match.'
            : 'More on either side widens the search. Not a score.';
        host.appendChild(note);
    }

    function renderAnalytics() {
        renderViewsChart();
        renderMatchChart();
        renderPipelineChart();
        renderCoverage();
    }

    // --- What is behind one arc -------------------------------------------
    // A share of a circle says how the pipeline is split. It cannot say which
    // partnerships make it up, so clicking a segment -- or its legend row --
    // lists them.
    //
    // The proposals come from /api/proposals rather than the dashboard's
    // payload, which carries only the five most recent. The ring counts all of
    // them, so opening the fourth-largest arc and finding three of its five
    // rows missing would be worse than not opening at all.
    const stageModal = document.getElementById('stageModal');
    const stageTitle = document.getElementById('stageModalTitle');
    const stageBody = document.getElementById('stageModalBody');

    /** Which proposals belong to a stage, by the same test the counts use. */
    function proposalsIn(step) {
        const all = proposals || [];
        if (step === 1) {
            return all.filter((p) => p.direction === 'outgoing' && p.status === 'pending');
        }
        if (step === 2) {
            return all.filter((p) => p.direction === 'incoming' && p.status === 'pending');
        }
        if (step === 3) return all.filter((p) => p.status === 'accepted');
        return all.filter((p) => p.status === 'completed');
    }

    function stageRow(p) {
        const gives = (p.you_give_labels || []).join(', ');
        const gets = (p.you_receive_labels || []).join(', ');
        const when = p.created_at
            ? new Date(p.created_at).toLocaleDateString('en-US', {
                month: 'short', day: 'numeric', year: 'numeric',
            })
            : '';
        return `
            <div class="stage-row">
                <div class="stage-row-head">
                    <span class="stage-who">${esc((p.counterpart || {}).name || 'Unnamed')}</span>
                    <span class="stage-when">${esc(when)}</span>
                </div>
                <dl class="stage-terms">
                    <div><dt>You give</dt><dd>${esc(gives || '—')}</dd></div>
                    <div><dt>You get</dt><dd>${esc(gets || '—')}</dd></div>
                </dl>
            </div>`;
    }

    function openStage(stage) {
        if (!stageModal) return;
        const rows = proposalsIn(stage.step);
        stageTitle.textContent = stage.label;
        stageBody.innerHTML = rows.length
            ? `<p class="stage-count">${rows.length} partnership${
                rows.length === 1 ? '' : 's'}</p>${rows.map(stageRow).join('')}`
            // The ring is drawn from the dashboard's counts and this list from
            // /api/proposals. They are two reads of the same rows and can
            // disagree if one arrives while a proposal is being answered in
            // another tab, so this says so rather than showing an empty panel
            // under a segment that is plainly not empty.
            : '<p class="chart-empty">Nothing to show here — the list may have '
              + 'changed since this page loaded. Reload to see it.</p>';
        stageModal.classList.add('active');
        document.body.style.overflow = 'hidden';
        window.dialogOpened(stageModal, stageModal.querySelector('.close-modal'));
    }

    function closeStage() {
        if (!stageModal) return;
        stageModal.classList.remove('active');
        document.body.style.overflow = 'auto';
        window.dialogClosed(stageModal);
    }

    if (stageModal) {
        // Cancel, the X and the backdrop share one way out. The backdrop is
        // the modal element itself; a click inside the container is not a
        // click-away.
        stageModal.addEventListener('click', (e) => {
            if (e.target === stageModal || e.target.closest('[data-close-stage]')) {
                closeStage();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && stageModal.classList.contains('active')) {
                closeStage();
            }
        });
    }

    // --- The table toggles ------------------------------------------------
    // One control per plot. What opening it does is the stylesheet's business
    // -- a sheet over the plot on one panel, a column beside it on the other
    // -- so all this does is say which state the region is in, in the two
    // places that have to agree: the class the CSS reads, and the
    // aria-expanded the button announces.
    //
    // hidden rather than a class: a table that is not open should be out of
    // the accessibility tree and out of the tab order, not merely invisible.
    document.querySelectorAll('[data-table-toggle]').forEach((button) => {
        const region = document.getElementById(button.dataset.tableToggle);
        const table = document.getElementById(button.getAttribute('aria-controls'));
        if (!region || !table) return;

        const label = button.querySelector('span');
        button.addEventListener('click', () => {
            const open = button.getAttribute('aria-expanded') !== 'true';
            button.setAttribute('aria-expanded', String(open));
            region.classList.toggle('is-open', open);
            table.hidden = !open;
            if (label) label.textContent = open ? 'Hide table' : 'View as table';
        });
    });

    renderAnalytics();

    // The plot is the one thing here drawn to a measured box, so it is the one
    // thing that has to be redrawn when the box changes. A ResizeObserver
    // rather than a window resize listener: it reports the element's real size
    // once the layout has settled -- which is what the first render needs and
    // what a load-time listener cannot give it -- and it also catches the
    // sizes a window resize does not, like the panel beside it growing.
    //
    // Guarded against re-entering: the redraw puts an SVG inside the box it is
    // measuring, and without the size check a render that nudged the box would
    // schedule another one forever.
    const plotHost = document.getElementById('viewsChart');
    if (plotHost && 'ResizeObserver' in window) {
        let lastW = 0;
        let lastH = 0;
        new ResizeObserver(() => {
            const w = plotHost.clientWidth;
            const h = plotHost.clientHeight;
            if (w === lastW && h === lastH) return;
            lastW = w;
            lastH = h;
            renderViewsChart();
        }).observe(plotHost);
    }
});
