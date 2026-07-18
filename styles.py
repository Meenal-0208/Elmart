"""
styles.py
---------
Central place for the Elmart "Bright White" theme used across the whole app:
clean white backgrounds with dark, high-contrast text and vivid pops of
color for accents, badges and charts. Every color, spacing and shadow value
used in the UI is defined here so the look-and-feel can be tweaked in one
place.

This module also defines the celebration "effects" (sound + on-screen
animation) that fire whenever a customer adds something to their cart:
  - Balloons + a cheerful chime when the order includes ANY discount
    (product discount and/or bulk-order discount).
  - Party crackers/confetti + a short pop sound when the order has
    no discount at all.
Both are implemented with the Web Audio API and plain CSS/JS animations, so
nothing external needs to be downloaded.
"""

# ----------------------------------------------------------------------------
# Palette - "Bright White"
# ----------------------------------------------------------------------------
PRIMARY = "#E64980"          # Vivid pink - primary brand color
PRIMARY_DARK = "#D6336C"     # Deeper pink for hover / accents
PRIMARY_DARKER = "#A61E4D"   # Strong deep rose for buttons / highlights
ACCENT = "#C2255C"           # Deep rose accent for headings / key numbers
ACCENT_DEEP = "#862E56"      # Darker rose, used for secondary emphasis

BACKGROUND = "#FFFFFF"       # Clean white page background
CARD_BG = "#FFFFFF"          # White card background
CARD_BG_ALT = "#F4F5F9"      # Very light grey (nested rows, inputs)
BORDER = "#E4E6EF"           # Soft light-grey border

SUCCESS = "#2F9E44"          # Green - used for savings / healthy status
WARNING = "#F08C00"          # Amber - used for "attention"
DANGER = "#E03131"           # Red - used only for critical/urgent flags
INFO = "#1971C2"             # Blue - informational accents
TRENDING = "#7048E8"         # Violet - trending badge

TEXT_PRIMARY = "#1A1A2E"     # Near-black navy - primary text (pops on white)
TEXT_SECONDARY = "#495057"   # Dark slate grey - secondary / caption text
TEXT_MUTED = "#868E96"       # Mid grey - least prominent text

# ----------------------------------------------------------------------------
# Shadows & radii
# ----------------------------------------------------------------------------
RADIUS = "16px"
RADIUS_SM = "10px"
SHADOW = "0 4px 18px rgba(26, 26, 46, 0.08)"
SHADOW_HOVER = "0 12px 32px rgba(198, 37, 92, 0.22)"

# ----------------------------------------------------------------------------
# Celebration effects: Web Audio sounds + CSS/JS balloon & cracker animations
# ----------------------------------------------------------------------------
EFFECTS_CSS = """
    @keyframes elmart-balloon-rise {
        0%   { transform: translateY(0) translateX(0) rotate(-4deg); opacity: 0.96; }
        8%   { opacity: 1; }
        100% { transform: translateY(-118vh) translateX(24px) rotate(6deg); opacity: 0; }
    }
    @keyframes elmart-cracker-burst {
        0%   { transform: translate(0, 0) scale(1); opacity: 1; }
        100% { transform: translate(var(--dx), calc(var(--dy) + 140px)) scale(0.25); opacity: 0; }
    }
    .elmart-fx-layer {
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 99999;
        overflow: hidden;
    }
"""

EFFECTS_JS = """
<script>
(function () {
    function playTone(freqs, durations, type, gain) {
        try {
            var Ctx = window.AudioContext || window.webkitAudioContext;
            var ctx = new Ctx();
            var t = ctx.currentTime;
            for (var i = 0; i < freqs.length; i++) {
                var osc = ctx.createOscillator();
                var g = ctx.createGain();
                osc.type = type;
                osc.frequency.setValueAtTime(freqs[i], t);
                g.gain.setValueAtTime(0, t);
                g.gain.linearRampToValueAtTime(gain, t + 0.02);
                g.gain.exponentialRampToValueAtTime(0.001, t + (durations[i] || 0.2));
                osc.connect(g);
                g.connect(ctx.destination);
                osc.start(t);
                osc.stop(t + (durations[i] || 0.2) + 0.03);
                t += (durations[i] || 0.2) * 0.85;
            }
            setTimeout(function () { ctx.close(); }, 2000);
        } catch (e) { /* audio not available - ignore silently */ }
    }

    function playDiscountChime() {
        playTone([523.25, 659.25, 783.99, 1046.5], [0.12, 0.12, 0.12, 0.28], 'triangle', 0.16);
    }

    function playPlainPop() {
        playTone([320, 200], [0.09, 0.16], 'square', 0.10);
    }

    function spawnBalloons() {
        var colors = ['#E64980', '#7048E8', '#FAB005', '#12B886', '#1971C2', '#F76707'];
        var layer = document.createElement('div');
        layer.className = 'elmart-fx-layer';
        document.body.appendChild(layer);
        var count = 14;
        for (var i = 0; i < count; i++) {
            var b = document.createElement('div');
            var color = colors[i % colors.length];
            var left = Math.random() * 96;
            var size = 34 + Math.random() * 22;
            var delay = Math.random() * 0.6;
            var duration = 2.6 + Math.random() * 1.4;
            b.style.cssText = 'position:absolute;bottom:-90px;left:' + left + 'vw;' +
                'width:' + size + 'px;height:' + (size * 1.2) + 'px;background:' + color + ';' +
                'border-radius:50% 50% 50% 50% / 60% 60% 40% 40%;' +
                'box-shadow: inset -6px -6px 10px rgba(0,0,0,0.15);' +
                'animation: elmart-balloon-rise ' + duration + 's ease-in ' + delay + 's forwards;' +
                'opacity:0.95;';
            var knot = document.createElement('div');
            knot.style.cssText = 'position:absolute;left:50%;bottom:-6px;width:0;height:0;' +
                'border-left:5px solid transparent;border-right:5px solid transparent;' +
                'border-top:7px solid ' + color + ';transform:translateX(-50%);';
            var string = document.createElement('div');
            string.style.cssText = 'position:absolute;left:50%;top:100%;width:1px;height:26px;' +
                'background:rgba(0,0,0,0.25);transform:translateX(-50%);';
            b.appendChild(knot);
            b.appendChild(string);
            layer.appendChild(b);
        }
        setTimeout(function () { layer.remove(); }, 4600);
    }

    function spawnCrackers() {
        var colors = ['#E03131', '#F08C00', '#2F9E44', '#1971C2', '#7048E8', '#E64980'];
        var layer = document.createElement('div');
        layer.className = 'elmart-fx-layer';
        document.body.appendChild(layer);
        var bursts = 3;
        for (var burst = 0; burst < bursts; burst++) {
            var cx = 18 + Math.random() * 64;
            var cy = 16 + Math.random() * 28;
            for (var i = 0; i < 18; i++) {
                var p = document.createElement('div');
                var angle = (Math.PI * 2 * i) / 18 + Math.random() * 0.3;
                var dist = 60 + Math.random() * 90;
                var dx = Math.cos(angle) * dist;
                var dy = Math.sin(angle) * dist;
                var color = colors[Math.floor(Math.random() * colors.length)];
                var shape = Math.random() > 0.5 ? '50%' : '2px';
                p.style.cssText = 'position:absolute;left:' + cx + 'vw;top:' + cy + 'vh;' +
                    'width:8px;height:8px;background:' + color + ';border-radius:' + shape + ';' +
                    '--dx:' + dx + 'px;--dy:' + dy + 'px;' +
                    'animation: elmart-cracker-burst 1s ease-out ' + (burst * 0.15) + 's forwards;';
                layer.appendChild(p);
            }
        }
        setTimeout(function () { layer.remove(); }, 2200);
    }

    window.elmartCelebrateDiscount = function () {
        playDiscountChime();
        spawnBalloons();
    };
    window.elmartCelebratePlain = function () {
        playPlainPop();
        spawnCrackers();
    };

    // ---- Flash-sale countdown ticker -------------------------------- //
    // Any element with class "rd-flash-countdown" and a data-end attribute
    // (epoch milliseconds) gets its text updated once a second. Server-side
    // refreshes recompute data-end from the live simulation every tick, so
    // this client-side ticker just smoothly interpolates between refreshes.
    function formatRemaining(ms) {
        if (ms <= 0) { return '⏳ Sale ending…'; }
        var totalSeconds = Math.ceil(ms / 1000);
        var m = Math.floor(totalSeconds / 60);
        var s = totalSeconds % 60;
        return '⏳ Ends in ' + m + ':' + (s < 10 ? '0' : '') + s;
    }
    function tickCountdowns() {
        var els = document.querySelectorAll('.rd-flash-countdown');
        for (var i = 0; i < els.length; i++) {
            var end = parseInt(els[i].getAttribute('data-end'), 10);
            if (!end) { continue; }
            els[i].textContent = formatRemaining(end - Date.now());
        }
    }
    if (!window.__elmartCountdownStarted) {
        window.__elmartCountdownStarted = true;
        setInterval(tickCountdowns, 1000);
    }
})();
</script>
"""

# ----------------------------------------------------------------------------
# Global CSS injected once into the page head
# ----------------------------------------------------------------------------
GLOBAL_CSS = f"""
<style>
    html, body {{
        background: {BACKGROUND} !important;
        font-family: 'Segoe UI', 'Poppins', sans-serif;
        color: {TEXT_PRIMARY};
    }}
    .q-page {{
        background: {BACKGROUND};
    }}
    * {{
        color: {TEXT_PRIMARY};
    }}
    ::-webkit-scrollbar {{
        width: 10px;
        height: 10px;
    }}
    ::-webkit-scrollbar-track {{
        background: {BACKGROUND};
    }}
    ::-webkit-scrollbar-thumb {{
        background: {PRIMARY_DARKER};
        border-radius: 10px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background: {ACCENT};
    }}

    .rd-card {{
        background: {CARD_BG};
        border-radius: {RADIUS};
        box-shadow: {SHADOW};
        border: 1px solid {BORDER};
        transition: all 0.2s ease-in-out;
    }}
    .rd-card:hover {{
        box-shadow: {SHADOW_HOVER};
        transform: translateY(-2px);
        border-color: {PRIMARY_DARKER};
    }}
    .rd-kpi-card {{
        background: linear-gradient(135deg, #FFFFFF 0%, #FBEFF3 100%);
        border-radius: {RADIUS};
        box-shadow: {SHADOW};
        border: 1px solid {BORDER};
        padding: 14px 16px;
    }}
    .rd-product-card {{
        background: {CARD_BG};
        border-radius: {RADIUS};
        box-shadow: {SHADOW};
        border: 1px solid {BORDER};
        padding: 10px;
        width: 100%;
    }}
    .rd-product-card:hover {{
        box-shadow: {SHADOW_HOVER};
        transform: translateY(-3px);
        border-color: {PRIMARY_DARKER};
    }}
    .rd-badge-flash {{
        background: {DANGER};
        color: #FFFFFF;
        border-radius: 20px;
        padding: 2px 10px;
        font-size: 11px;
        font-weight: 700;
    }}
    .rd-badge-trending {{
        background: {TRENDING};
        color: #FFFFFF;
        border-radius: 20px;
        padding: 2px 10px;
        font-size: 11px;
        font-weight: 700;
    }}
    .rd-badge-discount {{
        background: {ACCENT};
        color: #FFFFFF;
        border-radius: 20px;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 700;
    }}
    .rd-badge-bulk {{
        background: {SUCCESS};
        color: #FFFFFF;
        border-radius: 20px;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 700;
    }}
    .rd-scroll-panel {{
        height: calc(100vh - 20px);
        overflow-y: auto;
        overflow-x: hidden;
    }}
    .rd-logo-title {{
        font-weight: 800;
        font-size: 24px;
        color: {ACCENT};
        letter-spacing: 0.5px;
    }}
    .rd-section-title {{
        font-weight: 700;
        font-size: 16px;
        color: {ACCENT};
        margin-bottom: 4px;
    }}
    .rd-strike {{
        text-decoration: line-through;
        color: {TEXT_MUTED};
        font-size: 12px;
    }}
    .rd-price {{
        color: {ACCENT};
        font-weight: 800;
        font-size: 17px;
    }}
    .rd-bulk-tiers {{
        color: {INFO};
        font-size: 10.5px;
        font-weight: 600;
    }}
    .rd-total-line {{
        color: {SUCCESS};
        font-weight: 700;
        font-size: 12px;
    }}
    .rd-flash-countdown {{
        display: inline-block;
        color: {DANGER};
        background: #FFF0F0;
        border: 1px solid {DANGER};
        border-radius: 20px;
        padding: 2px 9px;
        font-size: 10.5px;
        font-weight: 700;
        margin-top: 3px;
    }}
    .rd-low-stock {{
        color: {WARNING};
        font-weight: 700;
        font-size: 11px;
    }}
    .rd-out-of-stock-chip {{
        display: inline-block;
        color: #FFFFFF;
        background: {TEXT_MUTED};
        border-radius: 8px;
        padding: 4px 10px;
        font-size: 11px;
        font-weight: 700;
        text-align: center;
    }}

    /* Quasar component overrides so inputs/selects/tables read as dark-on-white */
    .q-field__control, .q-field__native, .q-field__label, .q-field__marginal {{
        color: {TEXT_PRIMARY} !important;
    }}
    .q-field--outlined .q-field__control:before {{
        border-color: {BORDER} !important;
    }}
    .q-field--outlined.q-field--focused .q-field__control:before {{
        border-color: {PRIMARY_DARKER} !important;
    }}
    .q-field__control {{
        background: {CARD_BG_ALT} !important;
        border-radius: 10px;
    }}
    .q-placeholder::placeholder {{
        color: {TEXT_MUTED} !important;
    }}
    .q-menu {{
        background: {CARD_BG} !important;
        color: {TEXT_PRIMARY} !important;
        box-shadow: {SHADOW_HOVER};
    }}
    .q-item {{
        color: {TEXT_PRIMARY} !important;
    }}
    .q-item.q-manual-focusable--focused, .q-item:hover {{
        background: {CARD_BG_ALT} !important;
    }}

    {EFFECTS_CSS}
</style>
{EFFECTS_JS}
"""


def kpi_card_props() -> str:
    """Quasar classes/props applied to every KPI card."""
    return "rd-kpi-card"


def product_card_props() -> str:
    return "rd-product-card"
