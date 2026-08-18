# Financial model

The toolkit actually has two separate financial models, built for different jobs. It's easy to conflate them, so here's the distinction up front:

- **`ppa/financials.py`** is a quick, unlevered check: one blended annuity cash flow, no debt, no tax, no depreciation. This is what powers the LCOE/IRR/NPV numbers you see directly in the Optimization and Results tabs, right after a run.
- **`ppa/financial_model.py`** is the real project-finance model: multi-year, debt-sized off a DSCR target, with tax and depreciation schedules. This is what the dedicated Financial Model tab runs, and it's the one described in the rest of this page.

The levered model was ported from an Excel-based project-finance workbook used for real deal appraisal, simplified down to what's useful in a scenario-exploration tool (the original scenario-sweep tables, IRR heatmaps, working capital and terminal value were all dropped). On a reference scenario it reproduces the source workbook's Project IRR, Equity IRR and gearing within about 0.3 percentage points.

## Where the inputs come from

`EnergyInputs` is the bridge between a PyPSA run and the financial model: capacities, PPA volumes delivered, penalty volumes, excess (merchant) volumes, and volume-weighted capture prices. Merchant volumes and prices are split into solar hours (09:00–17:00) and non-solar hours, since solar and wind/battery output land in very different price buckets across most of the day. `energy_inputs_from_results()` takes a whole multi-year run and averages it into one representative operating year, since the financial model works from a single year escalated forward by indexation rather than replaying every simulated year individually.

`ProjectFinanceInputs` holds everything else: build cost, connection cost and devex per technology, fixed O&M, development and construction timelines, PPA tenor and tariff, penalty multiple, indexation rates (cost, PPA, and solar/non-solar merchant prices separately), debt tenor and rate, DSCR targets and gearing caps for the contracted and uncontracted revenue tranches, depreciation rates, and the corporate tax rate. Most of these seed from scenario defaults but are fully editable in the Financial Model tab.

One asymmetry worth knowing about: when inputs are seeded from a scenario, the scenario's single price-escalation rate fans out to cost inflation, PPA indexation and non-solar price inflation, but not to solar price inflation, which keeps its own separate default. If you're editing scenario-level escalation, check the solar merchant price assumption too.

## What the model actually computes

Roughly, in order:

1. **Timeline.** Development and construction periods per technology, back-aligned so everything finishes by financial close, then the operating life and PPA tenor laid out from there.
2. **Capital spend.** Devex and capex spread evenly across each technology's own development/construction window, indexed by cost inflation.
3. **Generation, revenue and opex.** PPA revenue and penalty cost from the contracted volumes; merchant solar and non-solar revenue from the excess volumes during the PPA term, and from total generation once it expires; fixed O&M plus a percentage-of-revenue ancillary cost.
4. **Debt sizing.** Cash available for debt service is split into contracted and uncontracted tranches by revenue share. Each tranche's debt capacity is the smaller of what a gearing cap and a DSCR target will support, discounted back at the debt rate. Debt draws down from financial close, with interest during construction accruing on the closing balance and capitalizing into the total debt. This is solved iteratively, since the drawdown and the interest on it are circular.
5. **Depreciation.** Straight-line, book and tax bases tracked separately (tax depreciation excludes devex, book depreciation includes it plus capitalized interest during construction).
6. **Tax.** Standard corporate tax with loss carry-forward, so early low- or negative-income years don't just vanish: they reduce tax in later years until used up.
7. **Returns.** Project IRR from free cash flow to the firm (pre-debt), Equity IRR from free cash flow to equity (post-debt-service). Both solved by bisection rather than a library IRR function, since the source workbook needed to match a specific convention here.
8. **DSCR and payback.** Minimum and average debt service coverage ratio across the debt tenor, and an equity payback period measured from the last sign change in cumulative cash flow (deliberately not the first, so a transient dip early in the project doesn't read as "never pays back").
9. **LCOE.** Annualized capital cost plus fixed O&M, divided by annual generation.

## Excel export

The Financial Model tab can export a live workbook, not just a snapshot of numbers. Revenue, opex, EBITDA, capex, depreciation, tax and cash flow are written as actual Excel formulas that recompute if you change an input cell. Debt drawdown and interest during construction are the one exception: because debt sizing is circular, they're written as pre-solved values with a note on the workbook's Notes sheet explaining that changing a cost assumption means re-running the toolkit to re-size debt, rather than expecting Excel to solve the circularity itself.

Each simulated year gets its own "Hourly" sheet with the full dispatch (generation by technology, market buy/sell, PPA delivery, penalty, and price), and the workbook's annual totals are computed from those sheets with SUM/SUMIFS formulas, so the numbers feeding the model are an auditable roll-up of the actual dispatch rather than hardcoded figures.

## Sensitivity analysis

The Sensitivity Analysis tab works entirely on top of the financial model's inputs. It never re-runs PyPSA, which means it's instant, but it also means it's the wrong tool for anything that would actually change dispatch: capacities, delivery share, and battery efficiency all require a re-run in the Optimization tab instead.

Two views on the same 24 parameters, grouped into capex, opex, revenue, indexation, debt, and tax/depreciation:

- **What-if panel.** Adjust any combination of parameters and see Project IRR, Equity IRR, gearing, NPV, total capex and minimum DSCR update immediately against the base case.
- **Tornado chart.** One-at-a-time sensitivity: each parameter is varied up and down by its own percentage range (wider for parameters with small base values, like indexation rates) and the resulting swing in a chosen output metric is plotted. Parameters with negligible impact on the selected metric are filtered out automatically rather than cluttering the chart. WACC, for instance, only feeds the NPV calculation and has no effect on IRR, so it disappears when IRR is the selected metric.

A few things fall out of the model that are worth knowing if you're using this for real analysis: the PPA tariff dominates Project IRR by a wide margin, PPA indexation is a distant second, and the tax depreciation rate is asymmetric: slowing it down hurts a lot, speeding it up barely helps, because the loss carry-forward mechanism already captures most of the benefit at the base rate.
