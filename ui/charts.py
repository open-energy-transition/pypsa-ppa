from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ppa.results import RevenueBreakdown

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


def make_price_series_chart(ts: "pd.DataFrame") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=ts.index,
            y=ts["ts_MktPrice"],
            mode="lines",
            name="Spot price",
            line=dict(color="#FF6F00", width=1),
        )
    )
    fig.update_layout(
        title="Market spot price — March 2025 (NSW)",
        xaxis_title="Time",
        yaxis_title="$/MWh",
        height=300,
        showlegend=False,
    )
    return fig
