"""Export a streamlined, *live* project-finance workbook.

Produces an ``.xlsx`` that mirrors :mod:`ppa.financial_model`: editable Inputs, a
pre-filled Energy (PyPSA interface) sheet, a transposed annual Model sheet and an
Outputs sheet. The revenue → EBITDA → depreciation → tax → cash-flow chain and
the IRR/NPV/DSCR outputs are written as **live Excel formulas**, so an analyst
can change a tariff, cost or rate and watch the returns update. The debt sizing
(front-loaded drawdown, IDC, DSCR tranche split) is circular by nature, so it is
written as toolkit-computed values that the live formulas reference — clearly
flagged so it can be overridden.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ppa.financial_model import (
    ProjectFinanceInputs,
    EnergyInputs,
    ProjectFinanceResult,
    _build_timeline,
)

# ── Styling ──────────────────────────────────────────────────────────────────
_TITLE = Font(bold=True, size=14, color="1F4E78")
_HEADER = Font(bold=True, color="FFFFFF")
_SECTION = Font(bold=True, size=11, color="1F4E78")
_INPUT_FONT = Font(color="0000CC")  # blue = editable input (convention)
_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
_PREFILL = PatternFill("solid", fgColor="E2EFDA")
_SECTION_FILL = PatternFill("solid", fgColor="DDEBF7")
_thin = Side(style="thin", color="D9D9D9")
_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def _pcol(period: int) -> int:
    """Spreadsheet column index for a 1-based model period (period 1 -> col D=4)."""
    return 3 + period


def export_financial_model(
    p: ProjectFinanceInputs,
    e: EnergyInputs,
    result: ProjectFinanceResult,
) -> bytes:
    wb = Workbook()
    inputs_cells = _write_inputs(wb, p)
    energy_cells = _write_energy(wb, e)
    _write_model(wb, p, e, result, inputs_cells, energy_cells)
    _write_outputs(wb, result)
    _write_notes(wb)

    # Recalculate formulas on open
    wb.calculation.calcMode = "auto"
    wb.calculation.fullCalcOnLoad = True

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Inputs sheet ──────────────────────────────────────────────────────────────


def _write_inputs(wb: Workbook, p: ProjectFinanceInputs) -> dict[str, str]:
    ws = wb.active
    ws.title = "Inputs"
    ws.column_dimensions["A"].width = 3
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 10
    ws.column_dimensions["E"].width = 60

    ws["B1"] = "Financial Model — Inputs"
    ws["B1"].font = _TITLE
    ws["B2"] = "Yellow cells are editable assumptions. Costs in €m/MW (€m/MWh for BESS)."
    ws["B2"].font = Font(italic=True, color="808080")

    cells: dict[str, str] = {}
    row = 4

    def section(title: str) -> None:
        nonlocal row
        ws.cell(row, 2, title).font = _SECTION
        for c in range(2, 6):
            ws.cell(row, c).fill = _SECTION_FILL
        row += 1

    def field(label: str, key: str, value, unit: str = "", note: str = "") -> None:
        nonlocal row
        ws.cell(row, 2, label)
        vc = ws.cell(row, 3, value)
        vc.fill = _INPUT_FILL
        vc.font = _INPUT_FONT
        vc.border = _BORDER
        if isinstance(value, float):
            vc.number_format = "#,##0.0000" if abs(value) < 10 else "#,##0.00"
        ws.cell(row, 4, unit).font = Font(color="808080")
        if note:
            ws.cell(row, 5, note).font = Font(italic=True, color="A0A0A0")
        cells[key] = f"Inputs!$C${row}"
        row += 1

    section("Build cost")
    field("Onshore wind build cost", "onsw_build_cost", p.onsw_build_cost, "€m/MW")
    field("Solar PV build cost", "pv_build_cost", p.pv_build_cost, "€m/MW")
    field("BESS build cost", "bess_build_cost", p.bess_build_cost, "€m/MWh")
    row += 1
    section("Connection cost")
    field("Onshore wind connection", "onsw_connection_cost", p.onsw_connection_cost, "€m/MW")
    field("Solar PV connection", "pv_connection_cost", p.pv_connection_cost, "€m/MW")
    field("BESS connection", "bess_connection_cost", p.bess_connection_cost, "€m/MWh")
    row += 1
    section("Project development cost (devex)")
    field("Onshore wind devex", "onsw_devex", p.onsw_devex, "€m/MW")
    field("Solar PV devex", "pv_devex", p.pv_devex, "€m/MW")
    field("BESS devex", "bess_devex", p.bess_devex, "€m/MWh")
    row += 1
    section("Fixed O&M (p.a.)")
    field("Onshore wind fixed O&M", "onsw_fixed_om", p.onsw_fixed_om, "€m/MW")
    field("Solar PV fixed O&M", "pv_fixed_om", p.pv_fixed_om, "€m/MW")
    field("BESS fixed O&M", "bess_fixed_om", p.bess_fixed_om, "€m/MWh")
    field("Ancillary services", "ancillary_pct", p.ancillary_pct, "% of revenue")
    row += 1
    section("Timing (years)")
    field("Model duration", "model_duration", p.model_duration, "years")
    field("Development start period", "development_start", p.development_start, "period")
    field("Onshore wind development", "onsw_dev_years", p.onsw_dev_years, "years")
    field("Solar PV development", "pv_dev_years", p.pv_dev_years, "years")
    field("BESS development", "bess_dev_years", p.bess_dev_years, "years")
    field("Onshore wind construction", "onsw_constr_years", p.onsw_constr_years, "years")
    field("Solar PV construction", "pv_constr_years", p.pv_constr_years, "years")
    field("BESS construction", "bess_constr_years", p.bess_constr_years, "years")
    field("Operating life", "operating_life", p.operating_life, "years")
    row += 1
    section("Revenue")
    field("PPA contract tenor", "ppa_tenor", p.ppa_tenor, "years")
    field("PPA tariff (base)", "ppa_tariff", p.ppa_tariff, "€/MWh")
    field("Penalty multiple", "penalty_multiple", p.penalty_multiple, "×")
    field("LGC / GO price", "lgc_price", p.lgc_price, "€/MWh")
    row += 1
    section("Indexation (% p.a.)")
    field("Indexation offset", "indexation_offset_years", p.indexation_offset_years, "years")
    field("Cost inflation", "cost_inflation", p.cost_inflation, "%")
    field("PPA & LGC indexation", "ppa_indexation", p.ppa_indexation, "%")
    field("Solar-hour price inflation", "solar_price_inflation", p.solar_price_inflation, "%")
    field("Non-solar-hour price inflation", "nonsolar_price_inflation", p.nonsolar_price_inflation, "%")
    row += 1
    section("Project finance")
    field("Debt repayment tenor", "debt_tenor", p.debt_tenor, "years")
    field("Debt rate", "debt_rate", p.debt_rate, "%")
    field("DSCR hurdle (contracted)", "dscr_contracted", p.dscr_contracted, "ratio")
    field("DSCR hurdle (uncontracted)", "dscr_uncontracted", p.dscr_uncontracted, "ratio")
    field("Max gearing (contracted)", "max_gearing_contracted", p.max_gearing_contracted, "%")
    field("Max gearing (uncontracted)", "max_gearing_uncontracted", p.max_gearing_uncontracted, "%")
    row += 1
    section("Depreciation & tax")
    field("Book depreciation rate", "book_depreciation_rate", p.book_depreciation_rate, "%")
    field("Tax depreciation rate", "tax_depreciation_rate", p.tax_depreciation_rate, "%")
    field("Corporate tax rate", "corp_tax_rate", p.corp_tax_rate, "%")
    field("Discount rate (WACC)", "discount_rate", p.discount_rate, "%")

    return cells


# ── Energy sheet (PyPSA interface) ───────────────────────────────────────────


def _write_energy(wb: Workbook, e: EnergyInputs) -> dict[str, str]:
    ws = wb.create_sheet("Energy")
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 10

    ws["B1"] = "PyPSA Energy Model Results (pre-filled)"
    ws["B1"].font = _TITLE
    ws["B2"] = f"Scenario: {e.name}"
    ws["B2"].font = Font(italic=True, color="808080")

    cells: dict[str, str] = {}
    row = 4

    def field(label: str, key: str, value, unit: str = "") -> None:
        nonlocal row
        ws.cell(row, 2, label)
        vc = ws.cell(row, 3, value)
        vc.fill = _PREFILL
        vc.border = _BORDER
        if isinstance(value, float):
            vc.number_format = "#,##0.00"
        ws.cell(row, 4, unit).font = Font(color="808080")
        cells[key] = f"Energy!$C${row}"
        row += 1

    field("Onshore wind capacity", "onsw_mw", e.onsw_mw, "MW")
    field("Solar PV capacity", "pv_mw", e.pv_mw, "MW")
    field("BESS power", "bess_mw", e.bess_mw, "MW")
    field("BESS energy", "bess_mwh", e.bess_mwh, "MWh")
    field("Offtaker load", "load_mw", e.load_mw, "MW")
    row += 1
    field("PPA delivered", "ppa_gwh", e.ppa_gwh, "GWh p.a.")
    field("Excess sold — solar hours", "excess_solar_gwh", e.excess_solar_gwh, "GWh p.a.")
    field("Excess sold — non-solar hours", "excess_nonsolar_gwh", e.excess_nonsolar_gwh, "GWh p.a.")
    field("Penalty (undelivered)", "penalty_gwh", e.penalty_gwh, "GWh p.a.")
    row += 1
    field("Total generation — solar hours", "total_solar_gwh", e.total_solar_gwh, "GWh p.a.")
    field("Total generation — non-solar hours", "total_nonsolar_gwh", e.total_nonsolar_gwh, "GWh p.a.")
    row += 1
    field("Merchant capture — solar hours", "sell_solar_price", e.sell_solar_price, "€/MWh")
    field("Merchant capture — non-solar hours", "sell_nonsolar_price", e.sell_nonsolar_price, "€/MWh")
    field("Market purchase price", "purchase_price", e.purchase_price, "€/MWh")
    field("Market purchase volume", "marketbuy_gwh", e.marketbuy_gwh, "GWh p.a.")

    return cells


# ── Model sheet (transposed; live formulas) ──────────────────────────────────


def _write_model(
    wb: Workbook,
    p: ProjectFinanceInputs,
    e: EnergyInputs,
    result: ProjectFinanceResult,
    I: dict[str, str],
    E: dict[str, str],
) -> None:
    ws = wb.create_sheet("Model")
    n = p.model_duration
    tl = _build_timeline(p)
    sc = result.schedule

    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 8

    ws["B1"] = "Annual Project-Finance Model"
    ws["B1"].font = _TITLE
    ws["B2"] = (
        "Revenue, opex, depreciation, tax and cash flows are live formulas. "
        "Debt drawdown/IDC and tranche split are toolkit-sized values (green)."
    )
    ws["B2"].font = Font(italic=True, color="808080")

    # Period header
    hdr = 4
    ws.cell(hdr, 2, "Period").font = _HEADER
    ws.cell(hdr, 2).fill = _HEADER_FILL
    ws.cell(hdr, 3, "Unit").font = _HEADER
    ws.cell(hdr, 3).fill = _HEADER_FILL
    for period in range(1, n + 1):
        c = ws.cell(hdr, _pcol(period), period)
        c.font = _HEADER
        c.fill = _HEADER_FILL
        c.alignment = Alignment(horizontal="center")

    R: dict[str, int] = {}
    row = hdr + 1

    def col(period: int) -> str:
        return get_column_letter(_pcol(period))

    def label_row(name: str, label: str, unit: str = "", section: bool = False) -> int:
        nonlocal row
        r = row
        cell = ws.cell(r, 2, label)
        if section:
            cell.font = _SECTION
            for cc in range(2, _pcol(n) + 1):
                ws.cell(r, cc).fill = _SECTION_FILL
        ws.cell(r, 3, unit).font = Font(color="808080", size=9)
        R[name] = r
        row += 1
        return r

    def put_formula(name: str, fn, fmt: str = "#,##0.0", value_fill: bool = False) -> None:
        r = R[name]
        for period in range(1, n + 1):
            cell = ws.cell(r, _pcol(period), fn(period, col(period)))
            cell.number_format = fmt
            if value_fill:
                cell.fill = _PREFILL

    def put_values(name: str, arr, fmt: str = "#,##0.0", value_fill: bool = True) -> None:
        r = R[name]
        for period in range(1, n + 1):
            cell = ws.cell(r, _pcol(period), round(float(arr[period - 1]), 6))
            cell.number_format = fmt
            if value_fill:
                cell.fill = _PREFILL

    # ── Flags (values) ───────────────────────────────────────────────────────
    label_row("flags", "Flags", section=True)
    label_row("ops_flag", "Operations flag", "0/1")
    put_values("ops_flag", sc["ops_flag"], "0")
    label_row("ppa_flag", "PPA flag", "0/1")
    put_values("ppa_flag", sc["ppa_flag"], "0")
    nonppa = sc["ops_flag"] - sc["ppa_flag"]
    label_row("nonppa_flag", "Post-PPA flag", "0/1")
    put_values("nonppa_flag", nonppa, "0")
    debt_flag = ((result.periods >= tl.ops_start) & (result.periods <= tl.debt_end)).astype(float)
    label_row("debt_flag", "Debt repayment flag", "0/1")
    put_values("debt_flag", debt_flag, "0")

    # ── Indexation (formulas) ─────────────────────────────────────────────────
    label_row("index", "Indexation multiples", section=True)
    label_row("cost_idx", "Cost inflation", "×")
    put_formula("cost_idx", lambda pr, cl: f"=(1+{I['cost_inflation']})^({cl}${hdr}+{I['indexation_offset_years']}-1)", "0.000")
    label_row("ppa_idx", "PPA & LGC", "×")
    put_formula("ppa_idx", lambda pr, cl: f"=(1+{I['ppa_indexation']})^({cl}${hdr}+{I['indexation_offset_years']}-1)", "0.000")
    label_row("solar_idx", "Solar-hour price", "×")
    put_formula("solar_idx", lambda pr, cl: f"=(1+{I['solar_price_inflation']})^({cl}${hdr}+{I['indexation_offset_years']}-1)", "0.000")
    label_row("nonsolar_idx", "Non-solar-hour price", "×")
    put_formula("nonsolar_idx", lambda pr, cl: f"=(1+{I['nonsolar_price_inflation']})^({cl}${hdr}+{I['indexation_offset_years']}-1)", "0.000")

    # ── Capital spend (live: cost inputs × capacity × indexation) ─────────────
    # Per-technology spend is spread evenly over each tech's development /
    # construction window. The timing fractions (0 or 1/n over the window) are
    # baked in per period, but the cost rates and capacities are live cell
    # references, so editing any build/connection/devex assumption flows through.
    def _fracs(first: int, last: int) -> list[float]:
        arr = [0.0] * n
        if last >= first:
            per = 1.0 / (last - first + 1)
            for pp in range(first, last + 1):
                arr[pp - 1] = per
        return arr

    onsw_dev_f = _fracs(*tl.tech_dev(p.onsw_dev_years))
    pv_dev_f = _fracs(*tl.tech_dev(p.pv_dev_years))
    bess_dev_f = _fracs(*tl.tech_dev(p.bess_dev_years))
    onsw_con_f = _fracs(*tl.tech_constr(p.onsw_constr_years))
    pv_con_f = _fracs(*tl.tech_constr(p.pv_constr_years))
    bess_con_f = _fracs(*tl.tech_constr(p.bess_constr_years))

    def _devex_fn(pr: int, cl: str) -> str:
        return (
            f"={cl}{R['cost_idx']}*("
            f"{onsw_dev_f[pr-1]}*{I['onsw_devex']}*{E['onsw_mw']}"
            f"+{pv_dev_f[pr-1]}*{I['pv_devex']}*{E['pv_mw']}"
            f"+{bess_dev_f[pr-1]}*{I['bess_devex']}*{E['bess_mwh']})"
        )

    def _capex_fn(pr: int, cl: str) -> str:
        return (
            f"={cl}{R['cost_idx']}*("
            f"{onsw_con_f[pr-1]}*({I['onsw_build_cost']}+{I['onsw_connection_cost']})*{E['onsw_mw']}"
            f"+{pv_con_f[pr-1]}*({I['pv_build_cost']}+{I['pv_connection_cost']})*{E['pv_mw']}"
            f"+{bess_con_f[pr-1]}*({I['bess_build_cost']}+{I['bess_connection_cost']})*{E['bess_mwh']})"
        )

    label_row("capital", "Capital spend", "€m", section=True)
    label_row("devex", "Devex", "€m")
    put_formula("devex", _devex_fn)
    label_row("capex", "Capex", "€m")
    put_formula("capex", _capex_fn)
    label_row("capital_spend", "Total capital spend", "€m")
    put_formula("capital_spend", lambda pr, cl: f"={cl}{R['devex']}+{cl}{R['capex']}")

    # ── Revenue (formulas) ────────────────────────────────────────────────────
    label_row("revenue", "Revenue", "€m", section=True)
    label_row("ppa_rev", "PPA revenue", "€m")
    put_formula("ppa_rev", lambda pr, cl: (
        f"={cl}{R['ppa_flag']}*{E['ppa_gwh']}*1000*({I['ppa_tariff']}*{cl}{R['ppa_idx']})/1000000"
    ))
    label_row("penalty_cost", "Penalty cost", "€m")
    put_formula("penalty_cost", lambda pr, cl: (
        f"={cl}{R['ppa_flag']}*{E['penalty_gwh']}*1000*({I['ppa_tariff']}*{I['penalty_multiple']}*{cl}{R['ppa_idx']})/1000000"
    ))
    label_row("merch_solar", "Merchant — solar hours", "€m")
    put_formula("merch_solar", lambda pr, cl: (
        f"=({cl}{R['ppa_flag']}*{E['excess_solar_gwh']}+{cl}{R['nonppa_flag']}*{E['total_solar_gwh']})"
        f"*1000*({E['sell_solar_price']}*{cl}{R['solar_idx']})/1000000"
    ))
    label_row("merch_nonsolar", "Merchant — non-solar hours", "€m")
    put_formula("merch_nonsolar", lambda pr, cl: (
        f"=({cl}{R['ppa_flag']}*{E['excess_nonsolar_gwh']}+{cl}{R['nonppa_flag']}*{E['total_nonsolar_gwh']})"
        f"*1000*({E['sell_nonsolar_price']}*{cl}{R['nonsolar_idx']})/1000000"
    ))
    label_row("lgc_rev", "LGC / GO revenue", "€m")
    put_formula("lgc_rev", lambda pr, cl: (
        f"=({cl}{R['ppa_flag']}*({E['excess_solar_gwh']}+{E['excess_nonsolar_gwh']})"
        f"+{cl}{R['nonppa_flag']}*({E['total_solar_gwh']}+{E['total_nonsolar_gwh']}))"
        f"*1000*({I['lgc_price']}*{cl}{R['ppa_idx']})/1000000"
    ))
    label_row("net_contracted", "Net contracted revenue", "€m")
    put_formula("net_contracted", lambda pr, cl: f"={cl}{R['ppa_rev']}-{cl}{R['penalty_cost']}")
    label_row("net_uncontracted", "Net uncontracted revenue", "€m")
    put_formula("net_uncontracted", lambda pr, cl: f"={cl}{R['merch_solar']}+{cl}{R['merch_nonsolar']}+{cl}{R['lgc_rev']}")
    label_row("total_rev", "Total revenue", "€m")
    put_formula("total_rev", lambda pr, cl: f"={cl}{R['net_contracted']}+{cl}{R['net_uncontracted']}")

    # ── Opex / EBITDA (formulas) ──────────────────────────────────────────────
    label_row("opex_sec", "Operating costs", "€m", section=True)
    fixed_om_expr = (
        f"({I['onsw_fixed_om']}*{E['onsw_mw']}+{I['pv_fixed_om']}*{E['pv_mw']}+{I['bess_fixed_om']}*{E['bess_mwh']})"
    )
    label_row("opex", "Total O&M expenses", "€m")
    put_formula("opex", lambda pr, cl: f"={cl}{R['ops_flag']}*{fixed_om_expr}+{I['ancillary_pct']}*{cl}{R['total_rev']}")
    label_row("ebitda", "EBITDA", "€m")
    put_formula("ebitda", lambda pr, cl: f"={cl}{R['total_rev']}-{cl}{R['opex']}")

    # ── Debt (toolkit values + interest formula reference) ────────────────────
    label_row("debt", "Debt schedule", "€m", section=True)
    label_row("debt_draw", "Debt drawdown", "€m")
    put_values("debt_draw", sc["debt_draw"])
    label_row("idc", "Interest during construction", "€m")
    put_values("idc", sc["idc"])
    label_row("interest", "Term loan interest", "€m")
    put_values("interest", sc["interest"])
    label_row("loan_repay", "Loan repayment", "€m")
    put_values("loan_repay", sc["loan_repay"])

    # ── Depreciation (live, straight-line capped at the asset base) ───────────
    firstcol, lastcol = col(1), col(n)
    label_row("dep", "Depreciation", "€m", section=True)

    # Asset bases (live): tax = capex only; book = devex + capex + capitalised IDC.
    label_row("tax_base", "Tax asset base", "€m")
    ws.cell(R["tax_base"], _pcol(1),
            f"=SUM({firstcol}{R['capex']}:{lastcol}{R['capex']})").number_format = "#,##0.0"
    label_row("book_base", "Book asset base", "€m")
    ws.cell(R["book_base"], _pcol(1), (
        f"=SUM({firstcol}{R['devex']}:{lastcol}{R['devex']})"
        f"+SUM({firstcol}{R['capex']}:{lastcol}{R['capex']})"
        f"+SUM({firstcol}{R['idc']}:{lastcol}{R['idc']})"
    )).number_format = "#,##0.0"

    def _dep_fn(self_row: int, base_row: int, rate_cell: str):
        # Straight-line at `rate` on the asset base, but never depreciate more
        # than the remaining book value (cumulative prior depreciation in-row).
        base = f"${firstcol}${base_row}"

        def fn(pr: int, cl: str) -> str:
            prior = "0" if pr == 1 else f"SUM(${firstcol}{self_row}:{col(pr-1)}{self_row})"
            return (
                f"={cl}{R['ops_flag']}*MIN({base}*{rate_cell},MAX({base}-{prior},0))"
            )
        return fn

    label_row("tax_dep", "Tax depreciation", "€m")
    put_formula("tax_dep", _dep_fn(R["tax_dep"], R["tax_base"], I["tax_depreciation_rate"]))
    label_row("book_dep", "Book depreciation", "€m")
    put_formula("book_dep", _dep_fn(R["book_dep"], R["book_base"], I["book_depreciation_rate"]))

    # ── P&L tax (live, with loss carry-forward) ───────────────────────────────
    label_row("pl", "Profit & tax", "€m", section=True)
    label_row("pbt", "Profit before tax", "€m")
    put_formula("pbt", lambda pr, cl: f"={cl}{R['ebitda']}-{cl}{R['interest']}-{cl}{R['book_dep']}")
    label_row("taxable", "Taxable income", "€m")
    put_formula("taxable", lambda pr, cl: f"={cl}{R['ebitda']}-{cl}{R['interest']}-{cl}{R['tax_dep']}")
    label_row("carry", "Carry-forward losses", "€m")
    put_formula("carry", lambda pr, cl: (
        f"=MIN(0,{cl}{R['taxable']})" if pr == 1
        else f"=MIN(0,{cl}{R['taxable']}+{col(pr-1)}{R['carry']})"
    ))
    label_row("tax", "Income tax", "€m")
    put_formula("tax", lambda pr, cl: (
        f"=MAX(0,{cl}{R['taxable']})*{I['corp_tax_rate']}" if pr == 1
        else f"=MAX(0,{cl}{R['taxable']}+{col(pr-1)}{R['carry']})*{I['corp_tax_rate']}"
    ))
    label_row("pat", "Profit after tax", "€m")
    put_formula("pat", lambda pr, cl: f"={cl}{R['pbt']}-{cl}{R['tax']}")

    # ── Returns (formulas) ────────────────────────────────────────────────────
    label_row("returns", "Returns", "€m", section=True)
    label_row("fcff", "FCFF (project)", "€m")
    put_formula("fcff", lambda pr, cl: (
        f"={cl}{R['ops_flag']}*({cl}{R['ebitda']}-{cl}{R['tax']})-{cl}{R['capital_spend']}"
    ))
    label_row("equity_spend", "Equity investment", "€m")
    put_formula("equity_spend", lambda pr, cl: f"={cl}{R['capital_spend']}-{cl}{R['debt_draw']}")
    label_row("fcfe", "FCFE (equity)", "€m")
    put_formula("fcfe", lambda pr, cl: (
        f"={cl}{R['ops_flag']}*({cl}{R['pat']}+{cl}{R['book_dep']}-{cl}{R['loan_repay']})-{cl}{R['equity_spend']}"
    ))
    label_row("cfads", "CFADS", "€m")
    put_formula("cfads", lambda pr, cl: f"={cl}{R['ops_flag']}*({cl}{R['ebitda']}-{cl}{R['tax']})")
    label_row("dscr", "DSCR", "ratio")
    put_formula("dscr", lambda pr, cl: (
        f"=IF(({cl}{R['interest']}+{cl}{R['loan_repay']})>0,"
        f"{cl}{R['cfads']}/({cl}{R['interest']}+{cl}{R['loan_repay']}),\"\")"
    ), "0.00")

    # remember key ranges for the Outputs sheet
    first, last = _pcol(1), _pcol(n)
    fl, ll = get_column_letter(first), get_column_letter(last)
    wb._fm_ranges = {  # type: ignore[attr-defined]
        "fcff": f"Model!{fl}{R['fcff']}:{ll}{R['fcff']}",
        "fcfe": f"Model!{fl}{R['fcfe']}:{ll}{R['fcfe']}",
        "ebitda": f"Model!{fl}{R['ebitda']}:{ll}{R['ebitda']}",
        "dscr": f"Model!{fl}{R['dscr']}:{ll}{R['dscr']}",
    }


# ── Outputs sheet ─────────────────────────────────────────────────────────────


def _write_outputs(wb: Workbook, result: ProjectFinanceResult) -> None:
    ws = wb.create_sheet("Outputs", 0)  # first sheet
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 16
    rng = getattr(wb, "_fm_ranges", {})

    ws["B1"] = "Financial Model — Key Outputs"
    ws["B1"].font = _TITLE
    ws["B2"] = f"Scenario: {result.energy.name}"
    ws["B2"].font = Font(italic=True, color="808080")

    row = 4

    def kpi(label: str, value, fmt: str, formula: str | None = None) -> None:
        nonlocal row
        ws.cell(row, 2, label).font = Font(bold=True)
        c = ws.cell(row, 3)
        c.value = formula if formula is not None else value
        c.number_format = fmt
        c.fill = _PREFILL
        c.border = _BORDER
        row += 1

    kpi("Project IRR (FCFF)", result.project_irr, "0.0%",
        f"=IFERROR(IRR({rng.get('fcff','')}),\"n/a\")" if rng.get("fcff") else None)
    kpi("Equity IRR (FCFE)", result.equity_irr, "0.0%",
        f"=IFERROR(IRR({rng.get('fcfe','')}),\"n/a\")" if rng.get("fcfe") else None)
    kpi("NPV @ WACC (project)", result.npv_project, "#,##0.0 \"€m\"")
    kpi("Gearing", result.gearing, "0.0%")
    kpi("Total funding (incl. IDC)", result.total_capex, "#,##0.0 \"€m\"")
    kpi("Total debt", result.total_debt, "#,##0.0 \"€m\"")
    kpi("Total equity", result.total_equity, "#,##0.0 \"€m\"")
    kpi("Minimum DSCR", result.min_dscr, "0.00")
    kpi("Average DSCR", result.avg_dscr, "0.00")
    kpi("Equity payback", result.payback_years, "0.0 \"yrs\"")
    kpi("LCOE", result.lcoe, "#,##0.0 \"€/MWh\"")

    ws.cell(row + 1, 2,
            "IRRs and the capex→depreciation→tax→cash-flow chain recompute live from the "
            "Model sheet. Debt sizing/IDC are pre-solved (circular); re-run the toolkit to "
            "re-size debt after large cost changes.").font = (
        Font(italic=True, color="A0A0A0", size=9))


# ── Notes sheet ───────────────────────────────────────────────────────────────


def _write_notes(wb: Workbook) -> None:
    ws = wb.create_sheet("Notes")
    ws.column_dimensions["B"].width = 100
    ws["B1"] = "Model notes & simplifications"
    ws["B1"].font = _TITLE
    notes = [
        "This workbook is a streamlined export of the PyPSA-PPA toolkit's project-finance model.",
        "",
        "Live (formula-driven, recompute on edit):",
        "  • Capex & devex — per-technology build/connection/devex cost × capacity ×",
        "    indexation (spend timing baked per period; edit a cost and it flows through).",
        "  • Indexation multipliers, all revenue lines, opex, EBITDA.",
        "  • Book/tax depreciation (straight-line, capped at the live asset base).",
        "  • Taxable income, loss carry-forward and income tax.",
        "  • PBT, PAT, FCFF, FCFE, DSCR, and the Project/Equity IRR outputs.",
        "",
        "Toolkit-sized values (green) — edit to override:",
        "  • Debt drawdown, IDC and the contracted/uncontracted tranche split are circular",
        "    (debt size depends on IDC which depends on drawdown), so they are pre-solved.",
        "    Changing capex therefore updates returns but not the debt amount — re-run the",
        "    toolkit to re-size debt.",
        "",
        "Simplifications (consistent with the source model):",
        "  • No working capital, no dividends, no terminal/decommissioning value.",
        "  • Development cost is refinanced by debt at financial close.",
        "  • One representative operating year, escalated by indexation.",
        "  • Solar hours defined as 09:00–17:00.",
    ]
    for i, line in enumerate(notes):
        ws.cell(2 + i, 2, line)
