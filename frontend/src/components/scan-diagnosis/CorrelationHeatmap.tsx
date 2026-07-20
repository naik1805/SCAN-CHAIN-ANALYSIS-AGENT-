"use client";



import {

  CORRELATION_FEATURES,

  chainSortKey,

  correlationCellColor,

  formatCorrelationInsight,

  formatFeatureLabel,

  maxAbsCorrelation,

  resolveFeatureGroups,

  sortChainsByStrongestCorrelation,

  type CorrelationFeatureGroup,

  type CorrelationSummary,

} from "@/lib/kpiDrillDown/correlationUtils";



function activeFeatures(

  correlations: Record<string, unknown>[],

  groups: CorrelationFeatureGroup[],

): CorrelationFeatureGroup[] {

  return groups

    .map((group) => ({

      ...group,

      features: group.features.filter((f) =>

        correlations.some(

          (row) =>

            (row.pearson_correlations as Record<string, number> | undefined)?.[f] != null,

        ),

      ),

    }))

    .filter((group) => group.features.length > 0);

}



export function CorrelationHeatmap({

  correlations,

  meta,

  variant = "heatmap",

  highlightChain,

}: {

  correlations: Record<string, unknown>[];

  meta?: Record<string, unknown>;

  variant?: "heatmap" | "matrix";

  highlightChain?: string;

}) {

  const summary = meta?.summary as CorrelationSummary | undefined;

  const groups = activeFeatures(

    correlations,

    resolveFeatureGroups(meta),

  );

  const flatFeatures =

    groups.flatMap((g) => g.features).length > 0

      ? groups.flatMap((g) => g.features)

      : [...CORRELATION_FEATURES].filter((f) =>

          correlations.some(

            (row) =>

              (row.pearson_correlations as Record<string, number> | undefined)?.[f] != null,

          ),

        );



  const globalStrongest = summary?.strongest_correlation;

  const rows = sortChainsByStrongestCorrelation(correlations);

  const insight = formatCorrelationInsight(summary);



  if (!rows.length) {

    return (

      <div className="glass-card flex h-80 items-center justify-center text-sm text-slate-500">

        No correlation data

      </div>

    );

  }



  return (

    <div className="glass-card space-y-3 p-4">

      <div className="flex flex-wrap items-start justify-between gap-3">

        <div className="space-y-1">

          <div className="text-xs text-slate-400">

            {summary?.chain_count ?? rows.length} chains ·{" "}

            {summary?.total_fail_records?.toLocaleString() ?? "—"} failure records

          </div>

          {insight ? (

            <p className="text-sm font-medium text-violet-200">{insight}</p>

          ) : (

            <p className="text-sm text-slate-500">No Pearson correlations computed.</p>

          )}

          {meta?.region_field_used === "die_label" ? (

            <p className="text-[11px] text-slate-500">

              Region chart uses die_label — failure_region is empty in logs.

            </p>

          ) : null}

          {meta?.topology_available === false ? (

            <p className="text-[11px] text-amber-500/80">

              Topology enrichment unavailable — clock/compression columns omitted.

            </p>

          ) : null}

        </div>

        {variant === "heatmap" ? <CorrelationLegend /> : null}

      </div>



      <div className="overflow-auto">

        <table className="w-full min-w-[720px] border-collapse text-xs">

          <thead>

            {groups.length > 1 ? (

              <tr>

                <th

                  className="sticky left-0 z-10 bg-[#0c111c] p-2 text-left text-slate-400"

                  rowSpan={2}

                >

                  Chain

                </th>

                {variant === "matrix" ? (

                  <th className="p-2 text-center text-slate-500" rowSpan={2}>

                    |r| max

                  </th>

                ) : null}

                {groups.map((group) => (

                  <th

                    key={group.id}

                    colSpan={group.features.length}

                    className="border-b border-border/80 p-2 text-center text-[10px] font-semibold uppercase tracking-wide text-slate-500"

                  >

                    {group.label}

                  </th>

                ))}

              </tr>

            ) : null}

            <tr>

              {groups.length <= 1 ? (

                <th className="sticky left-0 z-10 bg-[#0c111c] p-2 text-left text-slate-400">

                  Chain

                </th>

              ) : null}

              {groups.length <= 1 && variant === "matrix" ? (

                <th className="p-2 text-center text-slate-500">|r| max</th>

              ) : null}

              {flatFeatures.map((f) => (

                <th key={f} className="p-2 text-center text-slate-400">

                  {formatFeatureLabel(f)}

                </th>

              ))}

            </tr>

          </thead>

          <tbody>

            {rows.map((row) => {

              const pearson = (row.pearson_correlations || {}) as Record<string, number>;

              const chain = String(row.chain);

              const primary = String(row.primary_driver ?? row.primary_physical_driver ?? "");

              const isHighlightedChain = highlightChain === chain;

              const rowMax = maxAbsCorrelation(row);



              return (

                <tr

                  key={chain}

                  className={`border-t border-border/60 ${

                    isHighlightedChain ? "ring-1 ring-inset ring-primary/40" : ""

                  }`}

                >

                  <td className="sticky left-0 z-10 bg-[#0c111c] p-2 font-medium text-slate-200">

                    {chain}

                    {Number(row.failure_count) > 0 ? (

                      <span className="ml-1 text-[10px] text-slate-500">

                        ({Number(row.failure_count)})

                      </span>

                    ) : null}

                  </td>

                  {variant === "matrix" ? (

                    <td className="p-2 text-center tabular-nums text-slate-400">

                      {rowMax.toFixed(4)}

                    </td>

                  ) : null}

                  {flatFeatures.map((f) => {

                    const v = Number(pearson[f] ?? 0);

                    const isPrimary = f === primary;

                    const isGlobalStrongest =

                      globalStrongest?.chain === chain &&

                      globalStrongest?.metric === f;

                    return (

                      <td

                        key={f}

                        className={`p-2 text-center tabular-nums text-slate-100 ${

                          isPrimary || isGlobalStrongest

                            ? "font-semibold ring-1 ring-inset ring-white/25"

                            : ""

                        }`}

                        style={{ background: correlationCellColor(v) }}

                        title={

                          isPrimary

                            ? `Primary driver for ${chain}`

                            : isGlobalStrongest

                              ? "Strongest correlation overall"

                              : undefined

                        }

                      >

                        {v.toFixed(4)}

                      </td>

                    );

                  })}

                </tr>

              );

            })}

          </tbody>

        </table>

      </div>

    </div>

  );

}



function CorrelationLegend() {

  const stops = [-1, -0.5, 0, 0.5, 1];

  return (

    <div className="flex min-w-[180px] flex-col gap-1">

      <div className="text-[10px] uppercase tracking-wide text-slate-500">

        Pearson r

      </div>

      <div className="flex h-3 overflow-hidden rounded-md border border-border">

        {stops.slice(0, -1).map((start, idx) => {

          const mid = (start + stops[idx + 1]) / 2;

          return (

            <div

              key={start}

              className="flex-1"

              style={{ background: correlationCellColor(mid) }}

            />

          );

        })}

      </div>

      <div className="flex justify-between text-[10px] tabular-nums text-slate-500">

        <span>-1</span>

        <span>0</span>

        <span>+1</span>

      </div>

    </div>

  );

}



/** Compact heatmap for dashboard grid — chains sorted numerically. */

export function CorrelationHeatmapCompact({

  correlations,

  meta,

}: {

  correlations: Record<string, unknown>[];

  meta?: Record<string, unknown>;

}) {

  const rows = [...correlations].sort(

    (a, b) => chainSortKey(String(a.chain)) - chainSortKey(String(b.chain)),

  );

  return (

    <CorrelationHeatmap

      correlations={rows}

      meta={meta}

      variant="heatmap"

    />

  );

}


