/*
 * Chart runtime, injected into every generated chart page.
 *
 * The homepage picks a mode with ?mode=:
 *   preview      touch devices inside the page: look only, so one-finger
 *                swipes scroll the page instead of zooming the chart
 *   interactive  mouse inside the page: drag to zoom, range slider
 *   full         full screen (or the chart opened on its own): drag to pan
 *                on touch or zoom with a mouse, pinch to zoom the time axis
 *
 * In every mode the time presets work, and y axes follow the visible time
 * window (Plotly's own autorange always uses the whole history).
 */
(function (root, factory) {
    var api = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = api;
    } else {
        api.start(root);
    }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var DAY_MS = 864e5;
    var MODES = ["preview", "interactive", "full"];
    var PRESET_DAYS = { "1y": 365, "3y": 3 * 365 };
    var PRESET_LABELS = { "1y": "1Y", "3y": "3Y", "all": "All" };
    var NARROW_PX = 640;
    var MIN_PINCH_SPAN_MS = 14 * DAY_MS;

    // ---- Pure helpers (unit tested) ----

    function parseMode(search, isTopWindow, isCoarsePointer) {
        var match = /[?&]mode=([a-z]+)/.exec(search || "");
        if (match && MODES.indexOf(match[1]) !== -1) {
            return match[1];
        }
        if (isTopWindow) {
            return "full";
        }
        return isCoarsePointer ? "preview" : "interactive";
    }

    function parseTheme(search) {
        var match = /[?&]theme=([a-z]+)/.exec(search || "");
        return match && match[1] === "dark" ? "dark" : "light";
    }

    function parseColor(color) {
        if (!color || typeof color !== "string") return null;
        var value = color.trim().toLowerCase();
        if (value === "black") return [0, 0, 0, 1];
        if (value === "white") return [255, 255, 255, 1];
        var hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(value);
        if (hex) {
            var digits = hex[1].length === 3 ? hex[1].replace(/(.)/g, "$1$1") : hex[1];
            return [0, 2, 4].map(function (i) { return parseInt(digits.slice(i, i + 2), 16); }).concat([1]);
        }
        var rgb = /^rgba?\(([^)]+)\)$/.exec(value);
        if (rgb) {
            var parts = rgb[1].split(",").map(function (part) { return parseFloat(part); });
            if (parts.length >= 3) return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1];
        }
        return null;
    }

    // Near-black strokes and text disappear on a dark background.
    function isDarkColor(color) {
        var c = parseColor(color);
        return !!c && c[3] >= 0.3 && Math.max(c[0], c[1], c[2]) <= 60;
    }

    // Near-white fills (label and legend backgrounds) glare on a dark background.
    function isLightColor(color) {
        var c = parseColor(color);
        return !!c && c[3] >= 0.3 && Math.min(c[0], c[1], c[2]) >= 240;
    }

    function dataExtent(xs, ys, x0, x1, isLog) {
        var lo = Infinity;
        var hi = -Infinity;
        var n = Math.min(xs.length, ys.length);
        for (var i = 0; i < n; i++) {
            var x = xs[i];
            var raw = ys[i];
            if (!(x >= x0 && x <= x1) || raw === null || raw === undefined || raw === "") {
                continue;
            }
            var y = Number(raw);
            if (!isFinite(y)) {
                continue;
            }
            if (isLog) {
                if (y <= 0) {
                    continue;
                }
                y = Math.log10(y);
            }
            if (y < lo) lo = y;
            if (y > hi) hi = y;
        }
        return lo === Infinity ? null : [lo, hi];
    }

    function mergeExtents(extents) {
        var merged = null;
        extents.forEach(function (ext) {
            if (!ext) return;
            merged = merged ? [Math.min(merged[0], ext[0]), Math.max(merged[1], ext[1])] : ext.slice();
        });
        return merged;
    }

    function padExtent(ext, fraction) {
        if (!ext) return null;
        var pad = (ext[1] - ext[0]) * fraction;
        if (pad === 0) {
            pad = Math.abs(ext[0]) * fraction || fraction;
        }
        return [ext[0] - pad, ext[1] + pad];
    }

    function presetRange(preset, dataMin, dataMax) {
        if (!PRESET_DAYS[preset]) {
            return [dataMin, dataMax];
        }
        return [Math.max(dataMin, dataMax - PRESET_DAYS[preset] * DAY_MS), dataMax];
    }

    function availablePresets(spanMs) {
        var presets = [];
        if (spanMs > 1.5 * 365 * DAY_MS) presets.push("1y");
        if (spanMs > 4 * 365 * DAY_MS) presets.push("3y");
        if (presets.length) presets.push("all");
        return presets;
    }

    function zoomRange(range, centerFraction, scale, minSpan, bounds) {
        var span = range[1] - range[0];
        var maxSpan = bounds[1] - bounds[0];
        var nextSpan = Math.min(maxSpan, Math.max(minSpan, span / scale));
        var center = range[0] + centerFraction * span;
        var start = center - centerFraction * nextSpan;
        start = Math.min(Math.max(start, bounds[0]), bounds[1] - nextSpan);
        return [start, start + nextSpan];
    }

    // Log axes spanning many decades get one label per decade; Plotly's default
    // then labels every 2 and 5 as well, which clutters the axis.
    function logTickStep(axisType, tickmode, range) {
        if (axisType !== "log" || tickmode === "array" || !range) return undefined;
        return Math.abs(range[1] - range[0]) > 1.5 ? 1 : null;
    }

    // ---- Browser part ----

    function logDtick(axis, range) {
        return logTickStep(axis.type, axis.tickmode, range);
    }

    function isTopWindow(win) {
        try {
            return win.top === win;
        } catch (err) {
            return false;
        }
    }

    function isCoarsePointer(win) {
        return !!(win.matchMedia && win.matchMedia("(pointer: coarse)").matches);
    }

    function axisNames(fullLayout, letter) {
        return Object.keys(fullLayout).filter(function (key) {
            return new RegExp("^" + letter + "axis\\d*$").test(key);
        });
    }

    function traceAxisName(letter, ref) {
        return letter + "axis" + (ref && ref.length > 1 ? ref.slice(1) : "");
    }

    function start(win) {
        var doc = win.document;
        var mode = parseMode(win.location.search, isTopWindow(win), isCoarsePointer(win));
        var theme = parseTheme(win.location.search);
        doc.documentElement.setAttribute("data-chart-mode", mode);
        doc.documentElement.setAttribute("data-chart-theme", theme);
        if (/[?&]mode=/.test(win.location.search)) {
            doc.documentElement.setAttribute("data-embedded", "true");
        }
        waitForPlot(win, function (gd) {
            setup(win, gd, mode, theme);
        });
    }

    function waitForPlot(win, callback) {
        var attempts = 0;
        (function poll() {
            var gd = win.document.querySelector(".plotly-graph-div");
            if (gd && win.Plotly && gd._fullLayout && gd._fullLayout._size && gd.on) {
                callback(gd);
            } else if (attempts++ < 400) {
                win.setTimeout(poll, 50);
            }
        })();
    }

    function setup(win, gd, mode, theme) {
        var Plotly = win.Plotly;
        var doc = win.document;
        var touch = isCoarsePointer(win);
        var fullLayout = gd._fullLayout;
        var dateAxes = axisNames(fullLayout, "x").filter(function (name) {
            return fullLayout[name].type === "date";
        });
        var autoY = {};
        axisNames(fullLayout, "y").forEach(function (name) {
            var userAxis = gd.layout[name] || {};
            autoY[name] = !(Array.isArray(userAxis.range) && userAxis.autorange !== true);
        });
        var initialDtick = {};
        axisNames(fullLayout, "y").forEach(function (name) {
            initialDtick[name] = logDtick(fullLayout[name], fullLayout[name].range);
        });
        var bounds = dateAxes.length ? dataBounds(gd, dateAxes[0]) : null;
        var fitting = false;

        function currentRange() {
            var axis = gd._fullLayout[dateAxes[0]];
            return axis.range.map(axis.r2c).sort(function (a, b) { return a - b; });
        }

        function setTimeRange(range) {
            var update = {};
            dateAxes.forEach(function (name) {
                var axis = gd._fullLayout[name];
                update[name + ".range"] = [axis.c2r(range[0]), axis.c2r(range[1])];
            });
            return Plotly.relayout(gd, update);
        }

        function fitYAxes() {
            var layout = gd._fullLayout;
            var reset = dateAxes.every(function (name) { return layout[name].autorange; });
            var update = {};
            Object.keys(autoY).forEach(function (yName) {
                if (!autoY[yName]) return;
                if (reset) {
                    update[yName + ".autorange"] = true;
                    if (initialDtick[yName] !== undefined) update[yName + ".dtick"] = initialDtick[yName];
                    return;
                }
                var isLog = layout[yName].type === "log";
                var extents = gd._fullData.map(function (trace) {
                    if (trace.visible !== true || !trace.x || !trace.y) return null;
                    if (traceAxisName("y", trace.yaxis) !== yName) return null;
                    if (trace.hoverinfo === "skip" && trace.fill && trace.fill !== "none") return null;
                    var xAxis = layout[traceAxisName("x", trace.xaxis)];
                    if (!xAxis || xAxis.type !== "date") return null;
                    var visible = xAxis.range.map(xAxis.r2c);
                    var xs = Array.prototype.map.call(trace.x, function (x) { return xAxis.d2c(x); });
                    return dataExtent(xs, trace.y, Math.min(visible[0], visible[1]), Math.max(visible[0], visible[1]), isLog);
                });
                var range = padExtent(mergeExtents(extents), 0.06);
                if (range) {
                    update[yName + ".range"] = range;
                    var dtick = logDtick(layout[yName], range);
                    if (dtick !== undefined) update[yName + ".dtick"] = dtick;
                }
            });
            if (!Object.keys(update).length) return;
            fitting = true;
            Plotly.relayout(gd, update).then(
                function () { fitting = false; },
                function () { fitting = false; }
            );
        }

        var presetButtons = buildPresets(doc, bounds, function (preset) {
            setTimeRange(presetRange(preset, bounds[0], bounds[1]));
        });

        function syncPresets() {
            if (!presetButtons.length) return;
            var range = currentRange();
            presetButtons.forEach(function (button) {
                var target = presetRange(button.getAttribute("data-preset"), bounds[0], bounds[1]);
                var active = Math.abs(target[0] - range[0]) < DAY_MS && Math.abs(target[1] - range[1]) < DAY_MS;
                button.setAttribute("aria-pressed", active ? "true" : "false");
            });
        }

        gd.on("plotly_relayout", function (event) {
            if (fitting || !dateAxes.length) return;
            var timeChanged = Object.keys(event || {}).some(function (key) {
                return /^xaxis\d*\.(range|autorange)/.test(key);
            });
            if (!timeChanged) return;
            fitYAxes();
            syncPresets();
        });

        applyMode(win, gd, mode, touch, dateAxes, theme).then(syncPresets);

        if (mode === "full" && touch && dateAxes.length) {
            enablePinchZoom(win, gd, currentRange, setTimeRange, bounds);
        }
    }

    function dataBounds(gd, axisName) {
        var axis = gd._fullLayout[axisName];
        var lo = Infinity;
        var hi = -Infinity;
        gd._fullData.forEach(function (trace) {
            if (traceAxisName("x", trace.xaxis) !== axisName || !trace.x) return;
            Array.prototype.forEach.call(trace.x, function (x) {
                var value = axis.d2c(x);
                if (isFinite(value)) {
                    if (value < lo) lo = value;
                    if (value > hi) hi = value;
                }
            });
        });
        return lo === Infinity ? null : [lo, hi];
    }

    function buildPresets(doc, bounds, onSelect) {
        var container = doc.getElementById("chart-presets");
        if (!container || !bounds) return [];
        return availablePresets(bounds[1] - bounds[0]).map(function (preset) {
            var button = doc.createElement("button");
            button.type = "button";
            button.className = "chart-preset";
            button.setAttribute("data-preset", preset);
            button.setAttribute("aria-pressed", "false");
            button.textContent = PRESET_LABELS[preset];
            button.addEventListener("click", function () {
                onSelect(preset);
            });
            container.appendChild(button);
            return button;
        });
    }

    function applyMode(win, gd, mode, touch, dateAxes, theme) {
        var Plotly = win.Plotly;
        var fullLayout = gd._fullLayout;
        var update = {};
        var allAxes = axisNames(fullLayout, "x").concat(axisNames(fullLayout, "y"));

        if (mode === "preview") {
            update.dragmode = false;
            allAxes.forEach(function (name) { update[name + ".fixedrange"] = true; });
            dateAxes.forEach(function (name) { update[name + ".rangeslider.visible"] = false; });
        } else if (mode === "full" && touch) {
            update.dragmode = "pan";
        } else {
            update.dragmode = "zoom";
        }

        if (win.innerWidth < NARROW_PX) {
            update["font.size"] = 10;
            update["margin.l"] = 8;
            update["margin.r"] = 8;
            // One compact legend row above the plot instead of a box over the data
            update.legend = {
                orientation: "h",
                x: 0,
                xanchor: "left",
                y: 1.02,
                yanchor: "bottom",
                entrywidth: 0.5,
                entrywidthmode: "fraction",
                itemwidth: 30,
                bgcolor: "rgba(0,0,0,0)",
                borderwidth: 0,
                font: { size: 9 },
            };
            allAxes.forEach(function (name) { update[name + ".title.text"] = ""; });
        }

        axisNames(fullLayout, "y").forEach(function (name) {
            var dtick = logDtick(fullLayout[name], fullLayout[name].range);
            if (dtick !== undefined) update[name + ".dtick"] = dtick;
        });

        if (theme === "dark") {
            applyDarkTheme(gd, update, allAxes, dateAxes);
        }

        var config = {
            responsive: true,
            displaylogo: false,
            scrollZoom: false,
            displayModeBar: mode === "interactive" ? "hover" : false,
            modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toImage"],
        };

        Object.keys(update).forEach(function (key) {
            setPath(gd.layout, key, update[key]);
        });
        return Plotly.react(gd, gd.data, gd.layout, config);
    }

    var DARK = {
        surface: "#131c2e",
        text: "#c9d3e3",
        strong: "#e8edf5",
        grid: "rgba(255, 255, 255, 0.08)",
        line: "rgba(255, 255, 255, 0.2)",
        label: "rgba(19, 28, 46, 0.85)",
        slider: "#0f1726",
    };

    function lightenDark(color) {
        return isDarkColor(color) ? DARK.strong : color;
    }

    // Recolour the chart for the dark page; series colours stay as designed
    // except near-black ones, which would vanish.
    function applyDarkTheme(gd, update, allAxes, dateAxes) {
        update.paper_bgcolor = DARK.surface;
        update.plot_bgcolor = DARK.surface;
        update["font.color"] = DARK.text;
        update["legend.bgcolor"] = "rgba(0,0,0,0)";
        update["hoverlabel.bgcolor"] = "#1c2740";
        update["hoverlabel.bordercolor"] = DARK.line;
        update["hoverlabel.font.color"] = DARK.strong;
        allAxes.forEach(function (name) {
            update[name + ".gridcolor"] = DARK.grid;
            update[name + ".linecolor"] = DARK.line;
            update[name + ".zerolinecolor"] = DARK.line;
        });
        dateAxes.forEach(function (name) {
            update[name + ".rangeslider.bgcolor"] = DARK.slider;
        });

        gd.data.forEach(function (trace) {
            if (trace.line && trace.line.color) trace.line.color = lightenDark(trace.line.color);
            if (trace.marker) {
                if (typeof trace.marker.color === "string") trace.marker.color = lightenDark(trace.marker.color);
                if (trace.marker.line && trace.marker.line.color) trace.marker.line.color = lightenDark(trace.marker.line.color);
            }
        });
        (gd.layout.annotations || []).forEach(function (annotation) {
            if (isLightColor(annotation.bgcolor)) annotation.bgcolor = DARK.label;
            if (annotation.font && isDarkColor(annotation.font.color)) annotation.font.color = DARK.strong;
            if (isDarkColor(annotation.arrowcolor)) annotation.arrowcolor = DARK.strong;
        });
        (gd.layout.shapes || []).forEach(function (shape) {
            if (shape.line && isDarkColor(shape.line.color)) shape.line.color = DARK.line;
            if (isLightColor(shape.fillcolor)) shape.fillcolor = "rgba(255, 255, 255, 0.04)";
        });
    }

    function setPath(target, path, value) {
        var parts = path.split(".");
        var node = target;
        for (var i = 0; i < parts.length - 1; i++) {
            if (typeof node[parts[i]] !== "object" || node[parts[i]] === null) {
                node[parts[i]] = {};
            }
            node = node[parts[i]];
        }
        node[parts[parts.length - 1]] = value;
    }

    function enablePinchZoom(win, gd, currentRange, setTimeRange, bounds) {
        var pinch = null;
        var pending = null;

        function distance(touches) {
            return Math.abs(touches[0].clientX - touches[1].clientX) || 1;
        }

        function centerFraction(touches) {
            var size = gd._fullLayout._size;
            var rect = gd.getBoundingClientRect();
            var x = (touches[0].clientX + touches[1].clientX) / 2 - rect.left - size.l;
            return Math.min(1, Math.max(0, x / size.w));
        }

        gd.addEventListener("touchstart", function (event) {
            if (event.touches.length !== 2) return;
            event.preventDefault();
            event.stopPropagation();
            pinch = {
                startDistance: distance(event.touches),
                startRange: currentRange(),
                center: centerFraction(event.touches),
            };
        }, { capture: true, passive: false });

        gd.addEventListener("touchmove", function (event) {
            if (!pinch || event.touches.length !== 2) return;
            event.preventDefault();
            event.stopPropagation();
            var scale = distance(event.touches) / pinch.startDistance;
            pending = zoomRange(pinch.startRange, pinch.center, scale, MIN_PINCH_SPAN_MS, bounds);
            win.requestAnimationFrame(function () {
                if (pending) {
                    setTimeRange(pending);
                    pending = null;
                }
            });
        }, { capture: true, passive: false });

        gd.addEventListener("touchend", function (event) {
            if (event.touches.length < 2) pinch = null;
        }, { capture: true });
    }

    return {
        parseMode: parseMode,
        dataExtent: dataExtent,
        mergeExtents: mergeExtents,
        padExtent: padExtent,
        presetRange: presetRange,
        availablePresets: availablePresets,
        zoomRange: zoomRange,
        logTickStep: logTickStep,
        parseTheme: parseTheme,
        isDarkColor: isDarkColor,
        isLightColor: isLightColor,
        start: start,
    };
});
