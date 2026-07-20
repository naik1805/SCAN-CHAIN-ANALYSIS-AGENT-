export type SchematicCellKind = "upstream" | "break" | "downstream" | "ellipsis";

export interface SchematicCell {
  bit: number;
  label: string;
  kind: SchematicCellKind;
  cellPath: string;
}

export interface BreakSchematicModel {
  scanIn: string;
  scanOut: string;
  decompChannel: string;
  compChannel: string;
  chainLength: number;
  breakBit: number;
  locationStatus: string;
  cells: SchematicCell[];
  width: number;
}

function pinChannel(pin: unknown): string {
  const s = String(pin ?? "UNKNOWN");
  const m = s.match(/\[([^\]]+)\]/);
  return m ? m[1] : s;
}

function chainSortKey(chain: string): number {
  const digits = chain.replace(/\D/g, "");
  return digits ? Number(digits) : 0;
}

export function breakDieLabel(row: Record<string, unknown>): string {
  const lot = String(row.lot_id ?? "UNKNOWN");
  const file = String(row.source_file ?? "unknown.log");
  return `${lot} · ${file}`;
}

export function sortBreakRows(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  return [...rows].sort((a, b) => {
    const dieA = breakDieLabel(a);
    const dieB = breakDieLabel(b);
    if (dieA !== dieB) return dieA.localeCompare(dieB);
    return chainSortKey(String(a.chain ?? "")) - chainSortKey(String(b.chain ?? ""));
  });
}

export function buildBreakSchematic(row: Record<string, unknown>): BreakSchematicModel {
  const L = Number(row.chain_length) || 234;
  const N = Number(
    row.candidate_break_bit_position ?? row.break_bit_position ?? row.exact_break_bit_position ?? 0,
  );
  const pathPrefix = String(row.hierarchical_path ?? "U_core/unknown");
  const status = String(row.location_status ?? "UNCERTAIN");

  const upstream: SchematicCell[] = [];
  if (L - 1 - (N + 1) > 4) {
    upstream.push(
      { bit: L - 1, label: `FF ${L - 1}`, kind: "upstream", cellPath: `${pathPrefix}[${L - 1}]` },
      { bit: L - 2, label: `FF ${L - 2}`, kind: "upstream", cellPath: `${pathPrefix}[${L - 2}]` },
      { bit: -1, label: "...", kind: "ellipsis", cellPath: "" },
      { bit: N + 2, label: `FF ${N + 2}`, kind: "upstream", cellPath: `${pathPrefix}[${N + 2}]` },
      { bit: N + 1, label: `FF ${N + 1}`, kind: "upstream", cellPath: `${pathPrefix}[${N + 1}]` },
    );
  } else {
    for (let idx = L - 1; idx > N; idx -= 1) {
      upstream.push({
        bit: idx,
        label: `FF ${idx}`,
        kind: "upstream",
        cellPath: `${pathPrefix}[${idx}]`,
      });
    }
  }

  const breakCell: SchematicCell = {
    bit: N,
    label: `FF ${N}`,
    kind: "break",
    cellPath: `${pathPrefix}[${N}]`,
  };

  const downstream: SchematicCell[] = [];
  if (N > 4) {
    downstream.push(
      { bit: N - 1, label: `FF ${N - 1}`, kind: "downstream", cellPath: `${pathPrefix}[${N - 1}]` },
      { bit: N - 2, label: `FF ${N - 2}`, kind: "downstream", cellPath: `${pathPrefix}[${N - 2}]` },
      { bit: -1, label: "...", kind: "ellipsis", cellPath: "" },
      { bit: 1, label: "FF 1", kind: "downstream", cellPath: `${pathPrefix}[1]` },
      { bit: 0, label: "FF 0", kind: "downstream", cellPath: `${pathPrefix}[0]` },
    );
  } else {
    for (let idx = N - 1; idx >= 0; idx -= 1) {
      downstream.push({
        bit: idx,
        label: `FF ${idx}`,
        kind: "downstream",
        cellPath: `${pathPrefix}[${idx}]`,
      });
    }
  }

  const cells = [...upstream, breakCell, ...downstream];
  const xStart = 220;
  const xSpacing = 75;
  const lastCellEnd = xStart + (cells.length - 1) * xSpacing + 50;
  const compactorX = lastCellEnd + 25;
  const scanOutX = compactorX + 85 + 25;
  const width = scanOutX + 85 + 15;

  return {
    scanIn: String(row.scan_in ?? "UNKNOWN"),
    scanOut: String(row.scan_out ?? "UNKNOWN"),
    decompChannel: pinChannel(row.decompressor_pin),
    compChannel: pinChannel(row.compactor_pin),
    chainLength: L,
    breakBit: N,
    locationStatus: status,
    cells,
    width,
  };
}
