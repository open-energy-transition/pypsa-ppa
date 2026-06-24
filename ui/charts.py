from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ppa.counterfactuals import CounterfactualResult
from ppa.results import RevenueBreakdown
from ppa.scenario import Scenario

_COLORS = {
    "Wind": "#388E3C",
    "PV (direct)": "#F57C00",
    "BESS discharge": "#1565C0",
    "Buy from market": "#546E7A",
    "BESS charging": "#90CAF9",
}

_POSITIVE_COLS = ["Wind", "PV (direct)", "BESS discharge", "Buy from market"]
_NEGATIVE_COL = "BESS charging"


def _dual_axis_supply_mix(
    df: pd.DataFrame,
    x_col: str,
    title: str,
    ppaload_mw: float,
) -> go.Figure:
    y_max = max(
        df[_POSITIVE_COLS].sum(axis=1).max() if len(df) else 0,
        df[_NEGATIVE_COL].abs().max() if len(df) else 0,
        1.0,
    ) * 1.08

    fig = go.Figure()

    for col in _POSITIVE_COLS:
        if col in df.columns:
            fig.add_trace(
                go.Bar(
                    x=df[x_col],
                    y=df[col],
                    name=col,
                    marker_color=_COLORS.get(col),
                    yaxis="y",
                )
            )

    if _NEGATIVE_COL in df.columns:
        fig.add_trace(
            go.Bar(
                x=df[x_col],
                y=df[_NEGATIVE_COL],
                name=_NEGATIVE_COL,
                marker_color=_COLORS.get(_NEGATIVE_COL),
                yaxis="y2",
            )
        )

    fig.add_hline(
        y=ppaload_mw,
        line_dash="dash",
        line_color="#333333",
        line_width=1.5,
        annotation_text=f"PPA demand ({ppaload_mw:.0f} MW)",
        annotation_position="top right",
        annotation_font_size=10,
    )

    fig.update_layout(
        title=title,
        barmode="relative",
        height=420,
        xaxis_title=x_col.replace("_", " ").title(),
        yaxis=dict(
            title="MW (supply / market)",
            range=[-y_max, y_max],
        ),
        yaxis2=dict(
            title="MW (BESS charging)",
            overlaying="y",
            side="right",
            range=[-y_max, y_max],
            matches="y",
            showgrid=False,
            zeroline=False,
        ),
        legend_title="Source",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def make_supply_mix_24h_chart(avg_24h: pd.DataFrame, ppaload_mw: float) -> go.Figure:
    return _dual_axis_supply_mix(
        avg_24h,
        x_col="hour",
        title="Average hourly supply mix across the modelled period",
        ppaload_mw=ppaload_mw,
    )


def make_supply_mix_day_chart(
    day_df: pd.DataFrame,
    ppaload_mw: float,
    chosen_day: str,
) -> go.Figure:
    df = day_df.reset_index().rename(columns={"snapshot": "time"})
    return _dual_axis_supply_mix(
        df,
        x_col="time",
        title=f"Actual hourly supply mix — {chosen_day}",
        ppaload_mw=ppaload_mw,
    )


def make_revenue_breakdown_chart(revenue: RevenueBreakdown) -> go.Figure:
    labels = ["PPA Revenue", "Merchant Revenue", "Market Buy Cost", "Penalty Cost", "Net Revenue"]
    values = [
        revenue.ppa_revenue,
        revenue.excess_revenue,
        -revenue.market_purchase_cost,
        -revenue.penalty_cost,
        revenue.net_revenue,
    ]
    colors = ["#388E3C", "#66BB6A", "#E53935", "#B71C1C", "#1565C0"]
    measure = ["relative", "relative", "relative", "relative", "total"]

    fig = go.Figure(
        go.Waterfall(
            name="Revenue",
            orientation="v",
            measure=measure,
            x=labels,
            y=values,
            connector={"line": {"color": "rgb(63, 63, 63)"}},
            decreasing={"marker": {"color": "#E53935"}},
            increasing={"marker": {"color": "#388E3C"}},
            totals={"marker": {"color": "#1565C0"}},
        )
    )
    fig.update_layout(
        title="Revenue breakdown",
        yaxis_title="$ (period)",
        height=380,
        showlegend=False,
    )
    return fig


def make_soc_chart(soc: "pd.Series", bess_mwh: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=soc.index,
            y=soc.values,
            mode="lines",
            name="State of charge (MWh)",
            line=dict(color="#1565C0", width=1.5),
            fill="tozeroy",
            fillcolor="rgba(21, 101, 192, 0.15)",
        )
    )
    fig.add_hline(
        y=bess_mwh,
        line_dash="dash",
        line_color="#555",
        annotation_text=f"Full capacity ({bess_mwh:.0f} MWh)",
        annotation_position="top right",
        annotation_font_size=10,
    )
    fig.update_layout(
        title="BESS state of charge over the modelled period",
        xaxis_title="Time",
        yaxis_title="MWh",
        height=300,
        showlegend=False,
    )
    return fig


def make_price_series_chart(prices: "pd.Series | pd.DataFrame", title: str = "Market spot price") -> go.Figure:
    if hasattr(prices, "columns"):
        prices = prices["ts_MktPrice"]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=prices.index,
            y=prices,
            mode="lines",
            name="Spot price",
            line=dict(color="#FF6F00", width=1),
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Time",
        yaxis_title="€/MWh",
        height=300,
        showlegend=False,
    )
    return fig


def make_price_vs_ppa_chart(ts: "pd.DataFrame", ppa_price: float = 100.0) -> go.Figure:
    """Spot price time series with a flat PPA reference line — illustrates price certainty."""
    fig = go.Figure()

    # Shade negative-price hours to highlight market stress
    fig.add_trace(
        go.Scatter(
            x=ts.index,
            y=ts["ts_MktPrice"].clip(upper=0),
            mode="none",
            fill="tozeroy",
            fillcolor="rgba(229,57,53,0.15)",
            name="Negative prices",
            showlegend=True,
        )
    )
    fig.add_trace(
        go.Scatter(
            x=ts.index,
            y=ts["ts_MktPrice"],
            mode="lines",
            name="Wholesale spot price",
            line=dict(color="#FF6F00", width=1),
        )
    )
    fig.add_hline(
        y=ppa_price,
        line_dash="dash",
        line_color="#1565C0",
        line_width=2,
        annotation_text=f"PPA fixed price (€{ppa_price:.0f}/MWh)",
        annotation_position="top left",
        annotation_font_color="#1565C0",
        annotation_font_size=11,
    )
    fig.update_layout(
        title="European day-ahead spot price vs a fixed PPA tariff",
        xaxis_title="",
        yaxis_title="€/MWh",
        height=340,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(range=[ts["ts_MktPrice"].quantile(0.01) * 1.2, min(ts["ts_MktPrice"].max() * 1.05, 500)]),
    )
    return fig


def make_availability_profile_chart(ts: "pd.DataFrame") -> go.Figure:
    """Average wind and solar capacity factors by hour of day."""
    ts = ts.copy()
    ts["hour"] = ts.index.hour
    avg = ts.groupby("hour")[["ts_WindGen", "ts_PVGen"]].mean().reset_index()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=avg["hour"],
            y=avg["ts_WindGen"],
            mode="lines+markers",
            name="Wind",
            line=dict(color="#388E3C", width=2),
            marker=dict(size=5),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=avg["hour"],
            y=avg["ts_PVGen"],
            mode="lines+markers",
            name="Solar PV",
            line=dict(color="#F57C00", width=2),
            marker=dict(size=5),
        )
    )
    fig.add_hrect(
        y0=0, y1=avg["ts_WindGen"].min(),
        fillcolor="rgba(21,101,192,0.06)", line_width=0,
    )
    fig.update_layout(
        title="Average renewable availability by hour of day — central Germany",
        xaxis=dict(title="Hour of day", tickvals=list(range(0, 24, 3))),
        yaxis=dict(title="Capacity factor (0–1)", range=[0, 1]),
        height=320,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def make_ppa_obligation_chart(
    required_delivery_share: float,
    allowed_shortfall_share: float,
    ppaload_mw: float,
    pen_mult: float,
    ppa_price: float,
) -> go.Figure:
    """Horizontal stacked bar showing the PPA delivery obligation structure."""
    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=[required_delivery_share * 100],
            y=["Delivery obligation"],
            orientation="h",
            name=f"Must deliver ≥{required_delivery_share:.0%}",
            marker_color="#388E3C",
            text=f"Must deliver on average<br>≥{required_delivery_share:.0%} of contracted load",
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color="white", size=12),
        )
    )
    fig.add_trace(
        go.Bar(
            x=[allowed_shortfall_share * 100],
            y=["Delivery obligation"],
            orientation="h",
            name=f"Permitted gap ≤{allowed_shortfall_share:.0%}",
            marker_color="#FFA726",
            text=f"Permitted gap<br>≤{allowed_shortfall_share:.0%}",
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(color="#333", size=12),
        )
    )

    penalty_label = f"Beyond {allowed_shortfall_share:.0%}: penalty<br>{pen_mult:.1f}× tariff = €{ppa_price * pen_mult:.0f}/MWh"
    fig.add_annotation(
        x=101, y="Delivery obligation",
        text=penalty_label,
        showarrow=True,
        arrowhead=2,
        arrowcolor="#B71C1C",
        font=dict(color="#B71C1C", size=11),
        ax=60, ay=0,
        xanchor="left",
    )

    fig.update_layout(
        barmode="stack",
        title=f"PPA delivery obligation — {ppaload_mw:.0f} MW flat offtake",
        xaxis=dict(title="Share of total contracted load (%)", range=[0, 160], ticksuffix="%"),
        yaxis=dict(showticklabels=False),
        height=200,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.1, xanchor="left", x=0),
        margin=dict(l=20, r=20, t=60, b=40),
    )
    return fig


def make_counterfactual_bar_chart(cf: CounterfactualResult, scenario: Scenario) -> go.Figure:
    """Horizontal bar chart comparing effective €/MWh across procurement strategies."""
    strategies = ["Spot-only", f"Blended\n({scenario.cal_hedge_fraction:.0%} CAL)", "CAL Y+1", "PPA\n(offtaker)"]
    prices = [cf.spot_avg_price, cf.blended_avg_price, cf.cal_avg_price, cf.ppa_effective_price]
    colors = ["#FF6F00", "#FFA726", "#546E7A", "#1565C0"]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=prices,
            y=strategies,
            orientation="h",
            marker_color=colors,
            text=[f"€{p:.2f}/MWh" for p in prices],
            textposition="outside",
            textfont=dict(size=11),
            cliponaxis=False,
        )
    )
    fig.add_vline(
        x=scenario.ppa_price,
        line_dash="dash",
        line_color="#1565C0",
        line_width=1.5,
        annotation_text=f"PPA tariff (€{scenario.ppa_price:.0f}/MWh)",
        annotation_position="top",
        annotation_font_color="#1565C0",
        annotation_font_size=10,
    )
    x_max = max(prices) * 1.25
    fig.update_layout(
        title="Effective procurement cost by strategy",
        xaxis=dict(title="Effective €/MWh", range=[0, x_max]),
        yaxis=dict(autorange="reversed"),
        height=280,
        showlegend=False,
        margin=dict(l=140, r=60, t=50, b=40),
        plot_bgcolor="white",
    )
    return fig


def make_cumulative_cost_chart(cf: CounterfactualResult) -> go.Figure:
    """Cumulative procurement cost over the period for each strategy."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=cf.cumulative_spot.index,
            y=cf.cumulative_spot.values / 1e6,
            mode="lines",
            name="Spot-only",
            line=dict(color="#FF6F00", width=1.5),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=cf.cumulative_cal.index,
            y=cf.cumulative_cal.values / 1e6,
            mode="lines",
            name="CAL Y+1",
            line=dict(color="#546E7A", width=1.5, dash="dot"),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=cf.cumulative_ppa.index,
            y=cf.cumulative_ppa.values / 1e6,
            mode="lines",
            name="PPA (offtaker)",
            line=dict(color="#1565C0", width=2),
        )
    )
    fig.update_layout(
        title="Cumulative procurement cost over the modelled period",
        xaxis_title="",
        yaxis_title="Cumulative cost ($M)",
        height=320,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def make_multi_year_counterfactual_chart(
    years: list[int],
    ppa_prices: list[float],
    spot_prices: list[float],
    cal_prices: list[float],
    blended_prices: list[float],
) -> go.Figure:
    """Grouped bar chart: effective €/MWh per strategy per year."""
    fig = go.Figure()
    x = [str(y) for y in years]
    fig.add_trace(go.Bar(x=x, y=ppa_prices, name="PPA (offtaker)", marker_color="#1565C0"))
    fig.add_trace(go.Bar(x=x, y=spot_prices, name="Spot-only", marker_color="#FF6F00"))
    fig.add_trace(go.Bar(x=x, y=cal_prices, name="CAL Y+1", marker_color="#546E7A"))
    fig.add_trace(go.Bar(x=x, y=blended_prices, name="Blended", marker_color="#FFA726"))
    fig.update_layout(
        barmode="group",
        title="Effective procurement cost by year",
        xaxis_title="Year",
        yaxis_title="Effective €/MWh",
        height=380,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def make_portfolio_flow_chart(scenario: Scenario) -> go.Figure:
    """Plotly recreation of the portfolio structure and commercial energy flow diagram."""
    s = scenario
    BW, BH = 2.2, 0.82
    XA, XM, XR = 2.0, 6.5, 11.0

    shapes: list[dict] = []
    annotations: list[dict] = []

    def _box(cx: float, cy: float, text: str, fc: str, tc: str = "white") -> None:
        shapes.append(dict(
            type="rect",
            x0=cx - BW / 2, y0=cy - BH / 2,
            x1=cx + BW / 2, y1=cy + BH / 2,
            fillcolor=fc,
            line=dict(color="white", width=1.5),
            opacity=0.92,
            layer="above",
        ))
        annotations.append(dict(
            x=cx, y=cy,
            xref="x", yref="y",
            text=text.replace("\n", "<br>"),
            showarrow=False,
            font=dict(color=tc, size=9, family="Arial Black"),
            align="center",
        ))

    def _arrow(
        x1: float, y1: float, x2: float, y2: float,
        label: str = "", lc: str = "#555",
    ) -> None:
        annotations.append(dict(
            x=x2, y=y2,
            ax=x1, ay=y1,
            xref="x", yref="y",
            axref="x", ayref="y",
            showarrow=True,
            arrowhead=2, arrowsize=1, arrowwidth=1.5,
            arrowcolor=lc,
            text="",
        ))
        if label:
            annotations.append(dict(
                x=(x1 + x2) / 2, y=(y1 + y2) / 2 + 0.22,
                xref="x", yref="y",
                text=label,
                showarrow=False,
                font=dict(color=lc, size=8.5),
                bgcolor="rgba(255,255,255,0.8)",
                borderpad=2,
            ))

    # ── Boxes ─────────────────────────────────────────────────────────────────
    _box(XA, 6.0, f"Onshore Wind\n{s.onsw_mw:.0f} MW", "#388E3C")
    _box(XA, 4.6, f"Solar PV\n{s.pv_mw:.0f} MW AC", "#F57C00")

    if s.include_bess:
        _box(XA, 3.2, f"BESS\n{s.effective_bess_mw:.0f} MW / {s.effective_bess_mwh:.0f} MWh", "#1565C0")

    if s.enable_market_buy:
        _box(XA, 1.5, "Spot market\n(buy)", "#546E7A")

    _box(XM, 4.0, "IPP\nAggregation\nBus", "#6A1B9A")

    _box(XR, 6.0, f"PPA Offtaker\n{s.ppaload_mw:.0f} MW flat", "#BF360C")

    if s.enable_shortfall:
        _box(XR, 4.4, f"Allowed shortfall\n≤ {s.allowed_shortfall_share:.0%} of load", "#EF6C00", tc="#333")

    if s.enable_penalty:
        _box(XR, 2.8, f"Penalty\n{s.pen_mult:.1f}× €{s.ppa_price:.0f} = €{s.penalty_price:.0f}/MWh", "#B71C1C")

    if s.enable_market_sell:
        _box(XR, 1.2, "Excess sold\nto market", "#37474F")

    # ── Arrows: assets → aggregation ─────────────────────────────────────────
    _arrow(XA + BW / 2, 6.0,  XM - BW / 2, 4.3)
    _arrow(XA + BW / 2, 4.6,  XM - BW / 2, 4.1)
    if s.include_bess:
        _arrow(XA + BW / 2, 3.2, XM - BW / 2, 3.8)
    if s.enable_market_buy:
        _arrow(XA + BW / 2, 1.5, XM - BW / 2, 3.6,
               label=f"≤ {s.market_buy_share:.0%} of delivery", lc="#546E7A")

    # ── Arrows: aggregation → outcomes ────────────────────────────────────────
    _arrow(XM + BW / 2, 4.3, XR - BW / 2, 5.7,
           label=f"€{s.ppa_price:.0f}/MWh tariff", lc="#BF360C")

    if s.enable_market_sell:
        _arrow(XM + BW / 2, 3.7, XR - BW / 2, 1.4,
               label="excess", lc="#37474F")

    # ── Arrows: shortfall cascade ─────────────────────────────────────────────
    if s.enable_shortfall:
        _arrow(XR, 6.0 - BH / 2, XR, 4.4 + BH / 2,
               label="shortfall", lc="#EF6C00")
    if s.enable_penalty and s.enable_shortfall:
        _arrow(XR, 4.4 - BH / 2, XR, 2.8 + BH / 2,
               label="if cap exceeded", lc="#B71C1C")

    # ── Column headers ────────────────────────────────────────────────────────
    for cx, header in [
        (XA, "Physical portfolio"),
        (XM, "Commercial aggregation"),
        (XR, "Contractual outcomes"),
    ]:
        annotations.append(dict(
            x=cx, y=7.3,
            xref="x", yref="y",
            text=f"<b>{header}</b>",
            showarrow=False,
            font=dict(color="#333", size=11),
            bgcolor="#F5F5F5",
            bordercolor="#BDBDBD",
            borderwidth=1,
            borderpad=5,
        ))

    fig = go.Figure()
    fig.update_layout(
        shapes=shapes,
        annotations=annotations,
        xaxis=dict(range=[0, 13.5], showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(range=[0.3, 8.0], showgrid=False, zeroline=False, showticklabels=False),
        height=500,
        margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="white",
        title="Portfolio structure and commercial energy flows",
    )
    return fig
