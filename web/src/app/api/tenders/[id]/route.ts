import { NextResponse } from "next/server";
import { dbAvailabilityDetails } from "@/lib/db";
import {
  classifySoftwareBroad,
  classifySoftwareStrict,
} from "@/lib/registryClassifier";
import { getTenderDetailById } from "@/lib/queryTenders";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  const dbState = dbAvailabilityDetails();
  if (!dbState.ok) {
    return NextResponse.json(
      {
        error: "database_unavailable",
        message: dbState.reason,
        checkedPaths: dbState.checkedPaths,
      },
      { status: 503 },
    );
  }

  const { id: idRaw } = await ctx.params;
  const id = Number(idRaw);
  if (!Number.isFinite(id) || id < 1) {
    return NextResponse.json(
      { error: "bad_request", message: "invalid id" },
      { status: 400 },
    );
  }

  try {
    const row = getTenderDetailById(id);
    if (!row) {
      return NextResponse.json({ error: "not_found" }, { status: 404 });
    }

    const classifierInput = {
      objekti_procedurave: String(row.objekti_procedurave ?? ""),
      kodi_cpv_raw: String(row.kodi_cpv_raw ?? ""),
      tipi_procedures: String(row.tipi_procedures ?? ""),
    };
    const broad = classifySoftwareBroad(classifierInput);
    const strict = classifySoftwareStrict(classifierInput);

    return NextResponse.json({
      tender: row,
      software: {
        broad: broad.ok,
        strict: strict.ok,
        broad_reasons: broad.reasons,
        strict_excluded_reasons: strict.excludedReasons,
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "query failed";
    return NextResponse.json(
      { error: "server_error", message: msg },
      { status: 500 },
    );
  }
}
